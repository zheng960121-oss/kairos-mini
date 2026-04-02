"""
OpenClawIntegration - 与主 agent 共享上下文
参考 KAIROS 与 OpenClaw 的集成方式
"""

import os
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any


class OpenClawIntegration:
    """
    OpenClaw 集成 - 与主 agent 共享上下文
    - HEARTBEAT.md 被主 agent 定期读取
    - 小兰通过 Feishu 推送主动消息
    - 与主 agent 共享 MEMORY.md / 记忆系统
    """
    
    def __init__(self, workspace: Path, 
                 openclaw_cmd: str = "openclaw"):
        self.workspace = Path(workspace)
        self.openclaw_cmd = openclaw_cmd
        
        # 共享文件
        self.heartbeat_file = self.workspace / "HEARTBEAT.md"
        self.memory_file = self.workspace / "MEMORY.md"
        self.tasks_file = self.workspace / ".claude" / "scheduled_tasks.json"
        
        # 确保 .claude 目录存在
        self.tasks_file.parent.mkdir(parents=True, exist_ok=True)
    
    # ---- HEARTBEAT.md ----
    
    def write_heartbeat(self, items: List[str], 
                        title: Optional[str] = None):
        """
        写 HEARTBEAT.md 供主 agent 读取
        格式符合 OpenClaw heartbeat 规范
        """
        lines = []
        
        if title:
            lines.append(f"# {title}")
            lines.append("")
        
        lines.append(f"**更新时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("## 待处理事项")
        lines.append("")
        
        for item in items:
            lines.append(f"- [ ] {item}")
        
        lines.append("")
        lines.append("---")
        lines.append("*此文件由 kairos-mini 自动生成*")
        
        content = "\n".join(lines)
        self.heartbeat_file.write_text(content, encoding="utf-8")
    
    def read_heartbeat(self) -> Optional[str]:
        """读取主 agent 的 heartbeat 文件"""
        if self.heartbeat_file.exists():
            return self.heartbeat_file.read_text(encoding="utf-8")
        return None
    
    def append_to_heartbeat(self, item: str):
        """追加一项到 heartbeat（不重写整个文件）"""
        lines = [f"- [ ] {item}"]
        with open(self.heartbeat_file, "a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(lines))
    
    def clear_heartbeat(self):
        """清空 heartbeat"""
        if self.heartbeat_file.exists():
            self.heartbeat_file.unlink()
    
    # ---- 主动推送 ----
    
    def push_proactive_message(self, content: str,
                                channel: str = "feishu") -> bool:
        """
        主动推送到飞书（绕过文件队列）
        通过 OpenClaw CLI 或直接 webhook
        """
        # 方案 1: 通过 openclaw CLI 发送
        try:
            result = subprocess.run(
                [self.openclaw_cmd, "message", "--channel", channel, content],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # 方案 2: 写入 HEARTBEAT.md 作为 fallback
        self.write_heartbeat([content], title="🔥 主动推送")
        return True
    
    # ---- scheduled_tasks.json ----
    
    def read_scheduled_tasks(self) -> List[Dict]:
        """读取 .claude/scheduled_tasks.json"""
        if self.tasks_file.exists():
            try:
                return json.loads(self.tasks_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return []
        return []
    
    def write_scheduled_tasks(self, tasks: List[Dict]):
        """写入 scheduled_tasks.json"""
        self.tasks_file.write_text(
            json.dumps(tasks, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def add_scheduled_task(self, task: Dict) -> str:
        """添加定时任务"""
        tasks = self.read_scheduled_tasks()
        task_id = task.get('id') or str(int(datetime.now().timestamp() * 1000))
        task['id'] = task_id
        tasks.append(task)
        self.write_scheduled_tasks(tasks)
        return task_id
    
    def remove_scheduled_task(self, task_id: str) -> bool:
        """移除定时任务"""
        tasks = self.read_scheduled_tasks()
        original_len = len(tasks)
        tasks = [t for t in tasks if t.get('id') != task_id]
        if len(tasks) < original_len:
            self.write_scheduled_tasks(tasks)
            return True
        return False
    
    # ---- 内存共享 ----
    
    def read_shared_memory(self) -> str:
        """读取与主 agent 共享的 MEMORY.md"""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""
    
    def append_to_shared_memory(self, content: str):
        """追加到共享 MEMORY.md"""
        with open(self.memory_file, "a", encoding="utf-8") as f:
            f.write(f"\n{content}")
    
    # ---- OpenClaw Gateway 状态 ----
    
    def is_gateway_available(self) -> bool:
        """检查 OpenClaw Gateway 是否可用"""
        try:
            result = subprocess.run(
                [self.openclaw_cmd, "gateway", "status"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def get_gateway_status(self) -> Dict[str, Any]:
        """获取 Gateway 状态"""
        try:
            result = subprocess.run(
                [self.openclaw_cmd, "gateway", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass
        
        return {"available": False}
    
    # ---- Session 管理 ----
    
    def get_current_session_id(self) -> Optional[str]:
        """获取当前 session ID"""
        session_file = self.workspace / ".claude" / "current_session"
        if session_file.exists():
            return session_file.read_text(encoding="utf-8").strip()
        return None
    
    def switch_session(self, new_session_id: str) -> bool:
        """切换会话"""
        try:
            result = subprocess.run(
                [self.openclaw_cmd, "session", "switch", new_session_id],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
