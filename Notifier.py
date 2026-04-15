"""
Notifier - Proactive/Normal 双模式推送
参考 KAIROS BriefTool 设计
status='proactive' 推送到消息流，绕过文件队列
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class NotificationStatus(Enum):
    NORMAL = "normal"
    PROACTIVE = "proactive"  # AI 主动推送，立即送达


class NotificationChannel(Enum):
    FEISHU = "feishu"
    CONSOLE = "console"
    FILE = "file"
    HEARTBEAT = "heartbeat"  # 写入 HEARTBEAT.md


@dataclass
class Notification:
    id: str
    content: str
    status: str  # "normal" or "proactive"
    channel: str
    timestamp: str
    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class Notifier:
    """
    推送器 - 参考 KAIROS BriefTool
    - status=proactive: 立即推送
    - status=normal: 加入队列
    """
    
    TYPE_NORMAL = "normal"
    TYPE_PROACTIVE = "proactive"
    
    def __init__(self, queue_file: Optional[Path] = None,
                 heartbeat_file: Optional[Path] = None):
        self.pending: List[Notification] = []
        self.queue_file = queue_file
        self.heartbeat_file = heartbeat_file
        self._dispatcher: Optional[Callable] = None
        self._load_queue()
    
    def set_dispatcher(self, dispatcher: Callable[[Notification], None]):
        """
        设置分发器（用于实际发送通知）
        dispatcher 接收 Notification，返回是否成功
        """
        self._dispatcher = dispatcher
    
    def set_feishu_webhook(self, webhook_url: str):
        """设置飞书 webhook（用于 proactive 推送）"""
        self._feishu_webhook = webhook_url
    
    # ---- 发送通知 ----
    
    def notify(self, content: str, status: str = TYPE_NORMAL,
               channel: str = "feishu", title: Optional[str] = None,
               metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        发送通知
        - status=proactive: 立即推送
        - status=normal: 加入队列
        """
        notif = Notification(
            id=str(uuid.uuid4())[:8],
            content=content,
            status=status,
            channel=channel,
            timestamp=datetime.now().isoformat(),
            title=title,
            metadata=metadata or {}
        )
        
        if status == self.TYPE_PROACTIVE:
            self._push_immediately(notif)
        else:
            self.pending.append(notif)
            self._save_queue()
        
        return notif.id
    
    def _push_immediately(self, notif: Notification):
        """立即推送：模拟 BriefTool"""
        # 方案 1: 通过 dispatcher 发送
        if self._dispatcher:
            try:
                success = self._dispatcher(notif)
                if not success:
                    # dispatcher 失败，降级到队列
                    self.pending.append(notif)
            except Exception as e:
                print(f"[Notifier] dispatcher error: {e}, falling back to queue")
                self.pending.append(notif)
                self._save_queue()
            return
        
        # 方案 2: 写入 HEARTBEAT.md
        if self.heartbeat_file:
            self._write_heartbeat(notif)
            return
        
        # 方案 3: 打印到控制台（调试用）
        print(f"[PROACTIVE] {notif.content}")
    
    def _write_heartbeat(self, notif: Notification):
        """写入 HEARTBEAT.md 供主 agent 读取"""
        if not self.heartbeat_file:
            return
        
        lines = [
            f"## Proactive Alert - {notif.timestamp}",
            "",
            notif.content,
            "",
            f"---\n*Source: kairos-mini | ID: {notif.id}*"
        ]
        
        try:
            content = "\n".join(lines)
            self.heartbeat_file.write_text(content, encoding="utf-8")
        except IOError as e:
            print(f"[Notifier] failed to write heartbeat: {e}")
    
    # ---- 队列管理 ----
    
    def _load_queue(self):
        """从文件加载队列"""
        if self.queue_file and self.queue_file.exists():
            import json
            try:
                data = json.loads(self.queue_file.read_text(encoding="utf-8"))
                self.pending = [Notification(**n) for n in data]
            except (json.JSONDecodeError, IOError):
                self.pending = []
    
    def _save_queue(self):
        """保存队列到文件"""
        if not self.queue_file:
            return
        
        import json
        try:
            data = [n.__dict__ for n in self.pending]
            self.queue_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), 
                                        encoding="utf-8")
        except IOError as e:
            print(f"[Notifier] failed to save queue: {e}")
    
    def get_pending(self) -> List[Notification]:
        """获取待发送通知"""
        return self.pending.copy()
    
    def clear_pending(self):
        """清空待发送队列"""
        self.pending = []
        self._save_queue()
    
    def pop_pending(self) -> Optional[Notification]:
        """弹出一个待发送通知"""
        if self.pending:
            notif = self.pending.pop(0)
            self._save_queue()
            return notif
        return None
    
    # ---- 便捷方法 ----
    
    def tick_notification(self, tick_count: int, 
                          context: Optional[Dict] = None) -> str:
        """心跳通知（低优先级）"""
        content = f"❤ kairos-mini 心跳 #{tick_count}"
        if context:
            uptime = context.get('uptime', 0)
            content += f" | 运行: {uptime}s"
        
        return self.notify(content, status=self.TYPE_NORMAL, channel="console")
    
    def proactive_alert(self, content: str, 
                        title: Optional[str] = None) -> str:
        """主动告警（高优先级，立即推送）"""
        return self.notify(content, status=self.TYPE_PROACTIVE, 
                          channel="feishu", title=title)
    
    def info(self, content: str) -> str:
        """普通信息通知"""
        return self.notify(content, status=self.TYPE_NORMAL, channel="console")
    
    def success(self, content: str) -> str:
        """成功通知"""
        return self.notify(f"✅ {content}", status=self.TYPE_NORMAL, channel="console")
    
    def warning(self, content: str) -> str:
        """警告通知"""
        return self.notify(f"⚠️ {content}", status=self.TYPE_NORMAL, channel="console")
    
    def error(self, content: str) -> str:
        """错误通知"""
        return self.notify(f"❌ {content}", status=self.TYPE_NORMAL, channel="console")
    
    # ---- 批处理 ----
    
    def flush(self):
        """发送所有待处理通知"""
        while self.pending:
            notif = self.pop_pending()
            if notif and self._dispatcher:
                try:
                    self._dispatcher(notif)
                except Exception as e:
                    print(f"[Notifier] flush error: {e}")
                    # 重新放回队列
                    self.pending.insert(0, notif)
                    break


# ---- 全局单例 ----
_notifier: Optional[Notifier] = None


def get_notifier(queue_file: Optional[Path] = None,
                 heartbeat_file: Optional[Path] = None) -> Notifier:
    """获取 Notifier 单例（确保同一实例）"""
    global _notifier
    if _notifier is None:
        _notifier = Notifier(queue_file=queue_file, heartbeat_file=heartbeat_file)
    return _notifier
