"""
Memory Bus - 三层记忆系统
- Project Memory: 项目基本信息
- Session Memory: 当前会话状态
- Long-term Memory: 跨会话重要信息

支持文件锁，防止多进程同时写入导致数据损坏
"""

import json
import fcntl
import os
import sys
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

# 尝试导入日志（循环依赖，放后面处理）
_log = None

def _get_log():
    global _log
    if _log is None:
        try:
            from logger import get_logger
            _log = get_logger("memory")
        except Exception:
            _log = _DummyLog()
    return _log


class _DummyLog:
    """日志不可用时的降级"""
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass
    def debug(self, *a, **kw): pass


# 记忆文件路径
MEMORY_DIR = Path(__file__).parent / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

PROJECT_MEMORY_FILE = MEMORY_DIR / "project.json"
SESSION_MEMORY_FILE = MEMORY_DIR / "session.json"
LONGTERM_MEMORY_FILE = MEMORY_DIR / "longterm.json"


class FileLock:
    """文件锁封装（fcntl.flock）"""

    def __init__(self, file_path: Path, lock_type: str = "shared"):
        """
        Args:
            file_path: 要锁定的文件路径
            lock_type: "shared" 共享锁（读），"exclusive" 排他锁（写）
        """
        self.file_path = file_path
        self.lock_type = lock_type
        self._fd = None

    def __enter__(self):
        # 确保文件存在
        if not self.file_path.exists():
            self.file_path.write_text("{}", encoding="utf-8")
        self._fd = open(self.file_path, "r+", encoding="utf-8")
        if self.lock_type == "shared":
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_SH)
        else:
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX)
        return self._fd

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._fd:
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
            self._fd.close()


@contextmanager
def file_lock(path: Path, exclusive: bool = False, timeout: float = 5.0):
    """
    文件锁上下文管理器

    Args:
        path: 文件路径
        exclusive: True=排他锁（写），False=共享锁（读）
        timeout: 获取锁超时（秒）

    Usage:
        with file_lock(PROJECT_MEMORY_FILE, exclusive=True):
            # 安全写入
            pass
    """
    lock = FileLock(path, "exclusive" if exclusive else "shared")
    try:
        with lock:
            yield
    except BlockingIOError:
        _get_log().error(f"获取文件锁超时: {path}")
        raise TimeoutError(f"获取文件锁超时: {path}")


class MemoryBus:
    """三层记忆总线（线程安全/进程安全）"""

    def __init__(self):
        self._ensure_files()

    def _ensure_files(self):
        """确保记忆文件存在，初始化默认值"""
        # Project Memory 初始化
        if not PROJECT_MEMORY_FILE.exists():
            self.save_project_memory({
                "name": "KAIROS-mini",
                "version": "0.1.0",
                "description": "轻量级主动助手心跳引擎",
                "tech_stack": ["Python 3"],
                "created_at": datetime.now().isoformat()
            })

        # Session Memory 初始化
        if not SESSION_MEMORY_FILE.exists():
            self.save_session_memory({
                "session_id": None,
                "start_time": None,
                "last_active": None,
                "current_task": None,
                "tick_count": 0
            })

        # Long-term Memory 初始化
        if not LONGTERM_MEMORY_FILE.exists():
            self.save_longterm_memory({
                "events": [],
                "decisions": [],
                "learnings": []
            })

    # ===== Project Memory =====

    def get_project_memory(self) -> dict:
        """获取项目记忆"""
        try:
            with file_lock(PROJECT_MEMORY_FILE, exclusive=False):
                return json.loads(PROJECT_MEMORY_FILE.read_text())
        except Exception:
            return {}

    def save_project_memory(self, data: dict):
        """保存项目记忆"""
        with file_lock(PROJECT_MEMORY_FILE, exclusive=True):
            PROJECT_MEMORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def update_project_memory(self, updates: dict):
        """更新项目记忆"""
        current = self.get_project_memory()
        current.update(updates)
        current["updated_at"] = datetime.now().isoformat()
        self.save_project_memory(current)

    # ===== Session Memory =====

    def get_session_memory(self) -> dict:
        """获取会话记忆"""
        try:
            with file_lock(SESSION_MEMORY_FILE, exclusive=False):
                return json.loads(SESSION_MEMORY_FILE.read_text())
        except Exception:
            return {}

    def save_session_memory(self, data: dict):
        """保存会话记忆"""
        with file_lock(SESSION_MEMORY_FILE, exclusive=True):
            SESSION_MEMORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def update_session_memory(self, updates: dict):
        """更新会话记忆"""
        current = self.get_session_memory()
        current.update(updates)
        current["last_active"] = datetime.now().isoformat()
        self.save_session_memory(current)

    def start_session(self, session_id: str):
        """开始新会话"""
        self.update_session_memory({
            "session_id": session_id,
            "start_time": datetime.now().isoformat(),
            "tick_count": 0
        })

    def end_session(self):
        """结束当前会话"""
        self.update_session_memory({
            "session_id": None,
            "current_task": None
        })

    def increment_tick(self):
        """心跳计数 +1"""
        current = self.get_session_memory()
        current["tick_count"] = current.get("tick_count", 0) + 1
        current["last_active"] = datetime.now().isoformat()
        self.save_session_memory(current)

    # ===== Long-term Memory =====

    def get_longterm_memory(self) -> dict:
        """获取长期记忆"""
        try:
            with file_lock(LONGTERM_MEMORY_FILE, exclusive=False):
                return json.loads(LONGTERM_MEMORY_FILE.read_text())
        except Exception:
            return {"events": [], "decisions": [], "learnings": []}

    def save_longterm_memory(self, data: dict):
        """保存长期记忆"""
        with file_lock(LONGTERM_MEMORY_FILE, exclusive=True):
            LONGTERM_MEMORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def add_event(self, event_type: str, content: str, metadata: dict = None):
        """添加重要事件到长期记忆"""
        lt = self.get_longterm_memory()
        event = {
            "type": event_type,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        lt["events"].insert(0, event)  # 最新在前
        # 保留最近 100 条
        lt["events"] = lt["events"][:100]
        self.save_longterm_memory(lt)

    def add_decision(self, decision: str, reason: str = ""):
        """记录重要决策"""
        lt = self.get_longterm_memory()
        lt["decisions"].insert(0, {
            "decision": decision,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })
        lt["decisions"] = lt["decisions"][:50]
        self.save_longterm_memory(lt)

    def add_learning(self, learning: str):
        """记录学习到的经验"""
        lt = self.get_longterm_memory()
        lt["learnings"].insert(0, {
            "learning": learning,
            "timestamp": datetime.now().isoformat()
        })
        lt["learnings"] = lt["learnings"][:50]
        self.save_longterm_memory(lt)

    # ===== 统计信息 =====

    def get_stats(self) -> dict:
        """获取记忆系统统计"""
        lt = self.get_longterm_memory()
        session = self.get_session_memory()
        return {
            "total_events": len(lt.get("events", [])),
            "total_decisions": len(lt.get("decisions", [])),
            "total_learnings": len(lt.get("learnings", [])),
            "current_session_ticks": session.get("tick_count", 0),
            "session_id": session.get("session_id")
        }


# 全局单例
_memory_bus = None


def get_memory_bus() -> MemoryBus:
    """获取记忆总线单例"""
    global _memory_bus
    if _memory_bus is None:
        _memory_bus = MemoryBus()
    return _memory_bus


if __name__ == "__main__":
    # 测试代码
    mb = get_memory_bus()
    print("=== 记忆系统测试 ===")
    print(f"项目记忆: {mb.get_project_memory()}")
    print(f"会话记忆: {mb.get_session_memory()}")
    print(f"统计: {mb.get_stats()}")

    # 测试添加事件
    mb.add_event("test", "这是一条测试事件", {"source": "test"})
    print(f"长期记忆事件数: {mb.get_stats()['total_events']}")
