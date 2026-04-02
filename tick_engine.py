"""
Tick Engine - 心跳主循环
每隔一段时间触发检查，协调所有模块

支持：
- 心跳超时控制（单次心跳执行超时则跳过）
- atexit 退出清理
- 心跳时间戳文件（供 watchdog 检测）
- SIGTERM/SIGINT 信号处理
"""

import time
import uuid
import sys
import signal
import atexit
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

# 默认心跳间隔（秒）
DEFAULT_TICK_INTERVAL = 300  # 5分钟

# 心跳超时（秒），超时则跳过本次心跳
TICK_TIMEOUT = 60

# 心跳文件（供 watchdog 检测）
RUN_DIR = Path(__file__).parent / "run"
RUN_DIR.mkdir(exist_ok=True)
HEARTBEAT_FILE = RUN_DIR / "heartbeat.txt"
MAIN_PID_FILE = RUN_DIR / "kairos-main.pid"

# 日志
_log = None


def _get_log():
    global _log
    if _log is None:
        try:
            from logger import get_logger
            _log = get_logger("tick-engine")
        except Exception:
            class _DummyLog:
                def info(self, *a, **kw): print(f"[INF] {' '.join(str(x) for x in a)}")
                def warning(self, *a, **kw): print(f"[WRN] {' '.join(str(x) for x in a)}")
                def error(self, *a, **kw): print(f"[ERR] {' '.join(str(x) for x in a)}")
            _log = _DummyLog()
    return _log


class TickEngine:
    """
    心跳引擎

    核心功能：
    1. 定期触发心跳事件
    2. 管理心跳钩子（on_tick）
    3. 协调 Memory Bus、Notifier、Task Queue
    4. 心跳文件（watchdog 监控）
    """

    def __init__(self, interval: int = DEFAULT_TICK_INTERVAL):
        """
        初始化心跳引擎

        Args:
            interval: 心跳间隔（秒）
        """
        self.interval = interval
        self.running = False
        self.tick_count = 0
        self.session_id = str(uuid.uuid4())[:8]
        self.start_time = None
        self._shutdown_requested = False

        # 心跳钩子列表
        self.tick_hooks: list[Callable] = []

        # 引用其他模块（延迟初始化）
        self._memory = None
        self._notifier = None
        self._task_queue = None

        # 注册 atexit
        atexit.register(self._atexit_cleanup)

    def _atexit_cleanup(self):
        """atexit 清理"""
        try:
            _get_log().info("TickEngine atexit 清理...")
            if self._memory:
                self._memory.end_session()
        except Exception:
            pass

    # ===== 依赖注入 =====

    def set_memory(self, memory):
        """设置记忆模块"""
        self._memory = memory

    def set_notifier(self, notifier):
        """设置推送模块"""
        self._notifier = notifier

    def set_task_queue(self, task_queue):
        """设置任务队列"""
        self._task_queue = task_queue

    # ===== 钩子管理 =====

    def on_tick(self, hook: Callable):
        """
        注册心跳钩子

        Args:
            hook: 钩子函数，签名: hook(tick_count, context)
                  context 包含 memory, notifier, task_queue
        """
        self.tick_hooks.append(hook)

    def remove_hook(self, hook: Callable):
        """移除心跳钩子"""
        if hook in self.tick_hooks:
            self.tick_hooks.remove(hook)

    # ===== 生命周期 =====

    def start(self):
        """启动心跳引擎"""
        if self.running:
            _get_log().info("[TickEngine] 已经运行中")
            return

        self.running = True
        self.start_time = datetime.now()
        self.tick_count = 0

        # 写入 PID
        try:
            MAIN_PID_FILE.write_text(str(__import__("os").getpid()))
        except Exception:
            pass

        # 初始化会话
        if self._memory:
            self._memory.start_session(self.session_id)

        # 注册信号处理
        self._register_signal_handlers()

        _get_log().info(
            f"[TickEngine] 启动成功 (间隔: {self.interval}秒, 会话: {self.session_id})"
        )

        # 启动心跳循环
        self._run()

    def _register_signal_handlers(self):
        """注册信号处理器"""
        def signal_handler(sig, frame):
            sig_name = {signal.SIGTERM: "SIGTERM", signal.SIGINT: "SIGINT"}.get(sig, sig)
            _get_log().info(f"[TickEngine] 收到 {sig_name}，准备停止...")
            self._shutdown_requested = True
            self.running = False

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGHUP, signal_handler)

    def stop(self):
        """停止心跳引擎"""
        if not self.running:
            _get_log().info("[TickEngine] 未运行")
            return

        self.running = False
        self._shutdown_requested = True
        _get_log().info("[TickEngine] 已停止")

        # 结束会话
        if self._memory:
            try:
                self._memory.end_session()
            except Exception:
                pass

    def restart(self):
        """重启心跳引擎"""
        _get_log().info("[TickEngine] 重启中...")
        self.stop()
        time.sleep(1)
        self.__init__(self.interval)
        self.start()

    # ===== 内部方法 =====

    def _write_heartbeat(self):
        """写入心跳时间戳（供 watchdog 检测）"""
        try:
            pid = __import__("os").getpid()
            HEARTBEAT_FILE.write_text(f"{pid}|{time.time()}")
        except Exception:
            pass

    def _run(self):
        """心跳主循环"""
        # 写入初始心跳
        self._write_heartbeat()

        while self.running:
            try:
                self._tick_with_timeout()
            except KeyboardInterrupt:
                _get_log().info("\n[TickEngine] 收到键盘中断")
                break
            except Exception as e:
                _get_log().error(f"[TickEngine] 心跳循环异常: {e}")

            # 检查是否收到退出信号
            if self._shutdown_requested:
                _get_log().info("[TickEngine] 收到退出请求，退出循环")
                break

            # 等待下一次心跳
            time.sleep(self.interval)

        _get_log().info("[TickEngine] 心跳循环已退出")

    def _tick_with_timeout(self):
        """执行一次心跳（带超时控制）"""
        import signal

        class TickTimeout(Exception):
            pass

        def timeout_handler(signum, frame):
            raise TickTimeout(f"心跳执行超时 ({TICK_TIMEOUT}s)")

        # 设置超时
        if hasattr(signal, 'SIGALRM'):
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(TICK_TIMEOUT)

        try:
            self._tick()
        except TickTimeout as e:
            _get_log().error(f"[TickEngine] 心跳超时，跳过本次: {e}")
            if self._notifier:
                try:
                    self._notifier.health_alert(f"心跳执行超时 ({TICK_TIMEOUT}s) 已跳过")
                except Exception:
                    pass
        finally:
            if hasattr(signal, 'SIGALRM'):
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler or signal.SIG_DFL)

    def _tick(self):
        """执行一次心跳"""
        self.tick_count += 1
        tick_time = datetime.now()

        # 每次操作都更新心跳文件（让 watchdog 知道我们活着）
        self._write_heartbeat()

        _get_log().info(f"[TickEngine] ❤️ 心跳 #{self.tick_count} @ {tick_time.strftime('%H:%M:%S')}")

        # 1. 更新记忆
        if self._memory:
            try:
                self._memory.increment_tick()
            except Exception as e:
                _get_log().error(f"[TickEngine] 更新记忆失败: {e}")

        # 2. 执行任务队列
        task_results = []
        if self._task_queue:
            try:
                task_results = self._task_queue.process_all()
                if task_results:
                    _get_log().info(f"[TickEngine] 执行了 {len(task_results)} 个任务")
            except Exception as e:
                _get_log().error(f"[TickEngine] 执行任务队列失败: {e}")

        # 3. 发送心跳通知
        if self._notifier:
            try:
                self._notifier.tick_notification(
                    self.tick_count,
                    events=[{"task": t[0], "success": t[1], "msg": t[2]} for t in task_results]
                )
            except Exception as e:
                _get_log().error(f"[TickEngine] 发送心跳通知失败: {e}")

        # 4. 调用钩子
        context = {
            "tick_count": self.tick_count,
            "tick_time": tick_time,
            "memory": self._memory,
            "notifier": self._notifier,
            "task_queue": self._task_queue,
            "task_results": task_results,
            "session_id": self.session_id
        }

        for hook in self.tick_hooks:
            try:
                hook(self.tick_count, context)
            except Exception as e:
                _get_log().error(f"[TickEngine] 钩子执行异常: {e}")

        # 5. 检查是否有高优先级通知需要立即处理
        if self._notifier:
            try:
                pending = self._notifier.get_pending_notifications()
                high_priority = [n for n in pending if n.get("priority") == "high"]
                if high_priority:
                    _get_log().info(f"[TickEngine] 有 {len(high_priority)} 条高优先级通知")
            except Exception as e:
                _get_log().error(f"[TickEngine] 检查高优先级通知失败: {e}")

        # 再次更新心跳（任务执行完毕）
        self._write_heartbeat()

    # ===== 状态查询 =====

    def get_status(self) -> dict:
        """获取引擎状态"""
        return {
            "running": self.running,
            "tick_count": self.tick_count,
            "session_id": self.session_id,
            "interval": self.interval,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "hooks_registered": len(self.tick_hooks),
            "pending_tasks": self._task_queue.get_pending_tasks().__len__() if self._task_queue else 0,
            "pending_notifications": self._notifier.get_unread_count() if self._notifier else 0
        }

    def is_running(self) -> bool:
        """检查是否运行中"""
        return self.running

    # ===== 手动触发 =====

    def trigger_tick(self):
        """手动触发一次心跳"""
        if self.running:
            self._tick()
        else:
            _get_log().info("[TickEngine] 引擎未运行")


# 全局单例
_tick_engine = None


def get_tick_engine() -> TickEngine:
    """获取心跳引擎"""
    global _tick_engine
    if _tick_engine is None:
        _tick_engine = TickEngine()
    return _tick_engine


# ===== 示例钩子 =====

def example_hook(tick_count: int, context: dict):
    """示例钩子：每10次心跳打印统计"""
    if tick_count % 10 == 0:
        memory = context.get("memory")
        if memory:
            stats = memory.get_stats()
            _get_log().info(f"[Hook] 记忆统计: {stats}")


def health_check_hook(tick_count: int, context: dict):
    """示例钩子：检查系统健康（移除 psutil 硬依赖）"""
    if tick_count % 12 == 0:  # 每小时一次（假设5分钟间隔）
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=1)
            if cpu > 90:
                notifier = context.get("notifier")
                if notifier:
                    notifier.alert(f"CPU 使用率过高: {cpu}%")
        except ImportError:
            pass  # psutil 未安装就跳过


if __name__ == "__main__":
    # 测试代码
    engine = TickEngine(interval=5)  # 测试用5秒间隔

    print("=== 心跳引擎测试 ===")
    print(f"状态: {engine.get_status()}")

    # 注册钩子
    engine.on_tick(example_hook)

    print("\n运行3次心跳...")
    for i in range(3):
        engine._tick()
        time.sleep(1)

    print(f"\n最终状态: {engine.get_status()}")
