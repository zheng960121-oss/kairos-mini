"""
Task Queue - 任务队列
从文件读取待执行任务，执行后记录结果

支持：
- 文件锁（防止多进程同时写）
- scheduled_at 定时任务（真正按时间执行）
- 任务超时控制
- 连续失败报警
"""

import json
import fcntl
import sys
import signal
import atexit
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Callable, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

# 尝试导入日志
_log = None


def _get_log():
    global _log
    if _log is None:
        try:
            from logger import get_logger
            _log = get_logger("tasks")
        except Exception:
            class _DummyLog:
                def info(self, *a, **kw): pass
                def warning(self, *a, **kw): pass
                def error(self, *a, **kw): pass
            _log = _DummyLog()
    return _log


# 任务文件路径
TASK_DIR = Path(__file__).parent / "tasks"
TASK_DIR.mkdir(exist_ok=True)

# 待执行任务队列
TASK_QUEUE_FILE = TASK_DIR / "queue.json"

# 任务历史
TASK_HISTORY_FILE = TASK_DIR / "history.json"

# 连续失败计数文件
FAILURE_COUNT_FILE = TASK_DIR / "failure_count.json"

# 默认任务超时（秒）
DEFAULT_TASK_TIMEOUT = 300  # 5 分钟

# 连续失败报警阈值
CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 3


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskPriority(Enum):
    """任务优先级"""
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class Task:
    """任务定义"""
    id: str
    name: str
    description: str
    status: str
    priority: str
    created_at: str
    scheduled_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    timeout: int = DEFAULT_TASK_TIMEOUT
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(**data)


@contextmanager
def _file_lock(path: Path, exclusive: bool = False):
    """文件锁上下文管理器（fcntl.flock）"""
    if not path.exists():
        path.write_text("[]" if "queue" not in str(path) and "history" not in str(path) else "{}",
                        encoding="utf-8")
    try:
        fd = open(path, "r+", encoding="utf-8")
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            content = fd.read()
            data = json.loads(content) if content.strip() else (
                [] if "queue" in str(path) or "history" in str(path) else {}
            )
            yield data, fd
        finally:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
            fd.close()
    except BlockingIOError:
        _get_log().error(f"获取文件锁超时: {path}")
        raise TimeoutError(f"获取文件锁超时: {path}")


def _save_json_atomic(path: Path, data, lock_exclusive: bool = True):
    """原子写入 JSON（先写临时文件再 rename）"""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.rename(path)  # atomic on POSIX


class TaskQueue:
    """任务队列管理器（进程安全）"""

    def __init__(self):
        self._ensure_files()
        self._handlers = {}
        self._failure_count = self._load_failure_count()

    def _ensure_files(self):
        """确保文件存在"""
        if not TASK_QUEUE_FILE.exists():
            TASK_QUEUE_FILE.write_text("[]", encoding="utf-8")
        if not TASK_HISTORY_FILE.exists():
            TASK_HISTORY_FILE.write_text("[]", encoding="utf-8")
        if not FAILURE_COUNT_FILE.exists():
            FAILURE_COUNT_FILE.write_text("{}", encoding="utf-8")

    def _generate_id(self) -> str:
        """生成任务ID"""
        import time
        return f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}_{int(time.time() * 1000) % 1000}"

    # ===== 连续失败计数 =====

    def _load_failure_count(self) -> dict:
        """加载失败计数"""
        try:
            return json.loads(FAILURE_COUNT_FILE.read_text())
        except Exception:
            return {}

    def _save_failure_count(self):
        """保存失败计数"""
        FAILURE_COUNT_FILE.write_text(json.dumps(self._failure_count, ensure_ascii=False, indent=2))

    def _increment_failure(self, task_name: str) -> int:
        """增加失败计数，返回当前计数"""
        self._failure_count[task_name] = self._failure_count.get(task_name, 0) + 1
        self._save_failure_count()
        return self._failure_count[task_name]

    def _reset_failure(self, task_name: str):
        """重置失败计数"""
        if task_name in self._failure_count:
            del self._failure_count[task_name]
            self._save_failure_count()

    def _check_failure_alert(self, task_name: str):
        """检查是否需要报警"""
        count = self._failure_count.get(task_name, 0)
        if count >= CONSECUTIVE_FAILURE_ALERT_THRESHOLD:
            try:
                from notifier import get_notifier
                n = get_notifier()
                n.alert(
                    f"⚠️ 任务 [{task_name}] 连续失败 {count} 次！"
                    f"请检查日志和任务配置。"
                )
                _get_log().error(f"任务 [{task_name}] 连续失败 {count} 次，已报警")
            except Exception:
                pass

    # ===== 任务注册 =====

    def register_handler(self, task_name: str, handler: Callable):
        """
        注册任务处理器

        Args:
            task_name: 任务名称
            handler: 处理函数，接受 Task 对象，返回结果字符串
                     支持设置 timeout 属性控制超时时间
        """
        self._handlers[task_name] = handler

    # ===== 任务管理 =====

    def add_task(self, name: str, description: str = "", priority: str = "normal",
                 scheduled_at: str = None, metadata: dict = None,
                 max_retries: int = 3, timeout: int = DEFAULT_TASK_TIMEOUT) -> Task:
        """
        添加新任务

        Args:
            name: 任务名称（用于匹配处理器）
            description: 任务描述
            priority: 优先级 high/normal/low
            scheduled_at: 计划执行时间 (ISO格式字符串)，None=立即执行
            metadata: 额外数据
            max_retries: 最大重试次数
            timeout: 超时时间（秒）

        Returns:
            创建的 Task 对象
        """
        task = Task(
            id=self._generate_id(),
            name=name,
            description=description,
            status=TaskStatus.PENDING.value,
            priority=TaskPriority(priority).value,
            created_at=datetime.now().isoformat(),
            scheduled_at=scheduled_at,
            metadata=metadata or {},
            max_retries=max_retries,
            timeout=timeout
        )

        try:
            with _file_lock(TASK_QUEUE_FILE, exclusive=True) as (queue, fd):
                # 高优先级插入队列头部
                if priority == "high":
                    queue.insert(0, task.to_dict())
                else:
                    queue.append(task.to_dict())
                fd.seek(0)
                fd.truncate()
                fd.write(json.dumps(queue, ensure_ascii=False, indent=2))
            _get_log().info(f"任务已添加: {task.id} [{task.name}] scheduled={scheduled_at}")
        except Exception as e:
            _get_log().error(f"添加任务失败: {e}")
            raise

        return task

    def get_pending_tasks(self) -> list:
        """获取待执行任务列表（不过滤，已在 process_all 中处理）"""
        try:
            with _file_lock(TASK_QUEUE_FILE, exclusive=False) as (queue, fd):
                return list(queue)
        except Exception:
            return []

    def get_runnable_tasks(self) -> list:
        """
        获取可执行的任务（过滤掉未到时间的定时任务）
        """
        try:
            with _file_lock(TASK_QUEUE_FILE, exclusive=False) as (queue, fd):
                now = datetime.now()
                runnable = []
                delayed = []
                for t in queue:
                    if t["status"] == TaskStatus.PENDING.value:
                        if t.get("scheduled_at"):
                            try:
                                scheduled = datetime.fromisoformat(t["scheduled_at"])
                                if scheduled <= now:
                                    runnable.append(t)
                                else:
                                    delayed.append(t)
                            except Exception:
                                runnable.append(t)
                        else:
                            runnable.append(t)
                    else:
                        runnable.append(t)  # 非 pending 的也保留
                return runnable
        except Exception:
            return []

    def get_next_task(self) -> Optional[Task]:
        """获取下一个可执行任务（跳过未到时间的定时任务）"""
        try:
            with _file_lock(TASK_QUEUE_FILE, exclusive=False) as (queue, fd):
                now = datetime.now()
                for i, t in enumerate(queue):
                    if t["status"] != TaskStatus.PENDING.value:
                        continue
                    if t.get("scheduled_at"):
                        try:
                            scheduled = datetime.fromisoformat(t["scheduled_at"])
                            if scheduled > now:
                                _get_log().debug(f"任务 {t['id']} 定时未到: {t['scheduled_at']} > {now}")
                                continue
                        except Exception:
                            pass
                    return Task.from_dict(t)
                return None
        except Exception:
            return None

    def mark_running(self, task_id: str) -> bool:
        """标记任务为运行中"""
        try:
            with _file_lock(TASK_QUEUE_FILE, exclusive=True) as (queue, fd):
                updated = False
                for t in queue:
                    if t["id"] == task_id:
                        t["status"] = TaskStatus.RUNNING.value
                        t["started_at"] = datetime.now().isoformat()
                        updated = True
                        break
                if updated:
                    fd.seek(0)
                    fd.truncate()
                    fd.write(json.dumps(queue, ensure_ascii=False, indent=2))
                return updated
        except Exception:
            return False

    def mark_completed(self, task_id: str, result: str = ""):
        """标记任务完成"""
        try:
            with _file_lock(TASK_QUEUE_FILE, exclusive=True) as (queue, fd_q):
                history = list(queue)  # 复制
                remaining = []
                completed = None
                for t in queue:
                    if t["id"] == task_id:
                        t["status"] = TaskStatus.COMPLETED.value
                        t["completed_at"] = datetime.now().isoformat()
                        t["result"] = result
                        completed = t
                    else:
                        remaining.append(t)

                if completed:
                    # 写入历史
                    try:
                        with _file_lock(TASK_HISTORY_FILE, exclusive=True) as (hist, fd_h):
                            hist.insert(0, completed)
                            hist[:] = hist[:100]
                            fd_h.seek(0)
                            fd_h.truncate()
                            fd_h.write(json.dumps(hist, ensure_ascii=False, indent=2))
                    except Exception:
                        pass

                    # 重置失败计数
                    self._reset_failure(completed["name"])

                fd_q.seek(0)
                fd_q.truncate()
                fd_q.write(json.dumps(remaining, ensure_ascii=False, indent=2))
        except Exception as e:
            _get_log().error(f"标记任务完成失败: {e}")

    def mark_failed(self, task_id: str, error: str = "", is_timeout: bool = False):
        """标记任务失败"""
        try:
            with _file_lock(TASK_QUEUE_FILE, exclusive=True) as (queue, fd_q):
                remaining = []
                failed = None
                for t in queue:
                    if t["id"] == task_id:
                        t["retry_count"] = t.get("retry_count", 0) + 1
                        t["error"] = error

                        # 超时特殊处理
                        if is_timeout:
                            t["status"] = TaskStatus.TIMEOUT.value
                            t["completed_at"] = datetime.now().isoformat()
                            failed = t
                            _get_log().warning(f"任务超时: {task_id} [{t['name']}]")
                        elif t["retry_count"] < t.get("max_retries", 3):
                            t["status"] = TaskStatus.PENDING.value
                            t["started_at"] = None
                            remaining.append(t)
                        else:
                            t["status"] = TaskStatus.FAILED.value
                            t["completed_at"] = datetime.now().isoformat()
                            failed = t
                    else:
                        remaining.append(t)

                if failed:
                    # 写历史
                    try:
                        with _file_lock(TASK_HISTORY_FILE, exclusive=True) as (hist, fd_h):
                            hist.insert(0, failed)
                            hist[:] = hist[:100]
                            fd_h.seek(0)
                            fd_h.truncate()
                            fd_h.write(json.dumps(hist, ensure_ascii=False, indent=2))
                    except Exception:
                        pass

                    # 增加失败计数
                    count = self._increment_failure(failed["name"])
                    _get_log().warning(
                        f"任务失败: {task_id} [{failed['name']}] "
                        f"(第 {count} 次连续失败)"
                    )
                    # 检查是否报警
                    if count >= CONSECUTIVE_FAILURE_ALERT_THRESHOLD:
                        self._check_failure_alert(failed["name"])

                fd_q.seek(0)
                fd_q.truncate()
                fd_q.write(json.dumps(remaining, ensure_ascii=False, indent=2))
        except Exception as e:
            _get_log().error(f"标记任务失败失败: {e}")

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        try:
            with _file_lock(TASK_QUEUE_FILE, exclusive=True) as (queue, fd_q):
                remaining = []
                cancelled = None
                for t in queue:
                    if t["id"] == task_id:
                        t["status"] = TaskStatus.CANCELLED.value
                        t["completed_at"] = datetime.now().isoformat()
                        cancelled = t
                    else:
                        remaining.append(t)

                if cancelled:
                    try:
                        with _file_lock(TASK_HISTORY_FILE, exclusive=True) as (hist, fd_h):
                            hist.insert(0, cancelled)
                            hist[:] = hist[:100]
                            fd_h.seek(0)
                            fd_h.truncate()
                            fd_h.write(json.dumps(hist, ensure_ascii=False, indent=2))
                    except Exception:
                        pass

                fd_q.seek(0)
                fd_q.truncate()
                fd_q.write(json.dumps(remaining, ensure_ascii=False, indent=2))
                return cancelled is not None
        except Exception:
            return False

    def get_history(self, limit: int = 20) -> list:
        """获取任务历史"""
        try:
            with _file_lock(TASK_HISTORY_FILE, exclusive=False) as (hist, fd):
                return list(hist[:limit])
        except Exception:
            return []

    def get_stats(self) -> dict:
        """获取任务统计"""
        try:
            with _file_lock(TASK_QUEUE_FILE, exclusive=False) as (queue, fd_q):
                with _file_lock(TASK_HISTORY_FILE, exclusive=False) as (hist, fd_h):
                    stats = {
                        "pending": sum(1 for t in queue if t["status"] == TaskStatus.PENDING.value),
                        "running": sum(1 for t in queue if t["status"] == TaskStatus.RUNNING.value),
                        "total_queue": len(queue),
                        "total_history": len(hist),
                        "handlers_registered": list(self._handlers.keys()),
                        "failure_count": dict(self._failure_count),
                        "consecutive_failure_threshold": CONSECUTIVE_FAILURE_ALERT_THRESHOLD
                    }
                    for status in TaskStatus:
                        stats[f"history_{status.value}"] = sum(
                            1 for t in hist if t["status"] == status.value
                        )
                    return stats
        except Exception as e:
            _get_log().error(f"获取统计失败: {e}")
            return {"error": str(e)}

    # ===== 任务执行 =====

    def execute_next(self, timeout: int = None) -> Tuple[bool, str]:
        """
        执行下一个任务（带超时控制）

        Args:
            timeout: 任务执行超时（秒），None=使用任务自己的超时设置

        Returns:
            (success: bool, message: str)
        """
        import signal

        task = self.get_next_task()
        if not task:
            return False, "没有待执行任务"

        handler = self._handlers.get(task.name)
        if not handler:
            # 没有处理器，不失败也不重复执行，直接跳过
            _get_log().warning(f"没有注册任务处理器: [{task.name}]，跳过")
            self.cancel_task(task.id)
            return False, f"没有注册处理器: {task.name}"

        self.mark_running(task.id)

        # 设置超时
        effective_timeout = timeout or task.timeout
        if effective_timeout <= 0:
            effective_timeout = DEFAULT_TASK_TIMEOUT

        # 超时处理
        class TimeoutError(Exception):
            pass

        def timeout_handler(signum, frame):
            raise TimeoutError(f"任务执行超时 ({effective_timeout}s)")

        # 如果任务处理器没有声明自定义 timeout，用 signal
        old_alarm = None
        if effective_timeout and hasattr(signal, 'SIGALRM'):
            old_alarm = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(effective_timeout)

        try:
            result = handler(task)
            self.mark_completed(task.id, str(result))
            return True, f"完成: {result}"
        except TimeoutError as e:
            self.mark_failed(task.id, str(e), is_timeout=True)
            return False, f"超时: {e}"
        except Exception as e:
            self.mark_failed(task.id, str(e))
            return False, f"失败: {e}"
        finally:
            if effective_timeout and hasattr(signal, 'SIGALRM'):
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_alarm or signal.SIG_DFL)

    def process_all(self) -> list:
        """
        处理所有可执行任务

        Returns:
            [(task_id, success, message), ...]
        """
        results = []
        while True:
            task = self.get_next_task()
            if not task:
                break
            success, message = self.execute_next()
            results.append((task.id, success, message))
        return results


# 全局单例
_task_queue = None


def get_task_queue() -> TaskQueue:
    """获取任务队列单例"""
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue()
    return _task_queue


# ===== 内置任务处理器示例 =====

def check_system_health(task) -> str:
    """检查系统健康状态"""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        return f"CPU: {cpu}%, 内存: {mem}%, 磁盘: {disk}%"
    except ImportError:
        return "psutil 未安装，跳过系统健康检查"


def example_notification_task(task) -> str:
    """发送示例通知"""
    try:
        from notifier import get_notifier
        n = get_notifier()
        n.info(f"来自任务的通知: {task.description}")
        return "通知已发送"
    except Exception as e:
        return f"发送失败: {e}"


if __name__ == "__main__":
    # 测试代码
    tq = get_task_queue()

    print("=== 任务队列测试 ===")

    # 注册内置处理器
    tq.register_handler("check_health", check_system_health)
    tq.register_handler("notify", example_notification_task)

    # 添加测试任务
    tq.add_task("notify", "测试通知任务", priority="normal")
    tq.add_task("check_health", "检查系统健康", priority="low")

    print(f"待执行任务: {tq.get_pending_tasks()}")
    print(f"统计: {tq.get_stats()}")

    # 执行所有任务
    print("\n执行任务...")
    results = tq.process_all()
    for task_id, success, msg in results:
        print(f"  [{success}] {task_id}: {msg}")

    print(f"\n任务历史: {tq.get_history()}")
