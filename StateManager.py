"""
StateManager - 全局状态单例 + Signal 回调
参考 KAIROS state.ts 设计
"""

import os
import uuid
from datetime import datetime
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
import fcntl


@dataclass
class SkillInfo:
    skill_name: str
    skill_path: str
    content: str
    invoked_at: str
    agent_id: Optional[str] = None


@dataclass
class SessionCronTask:
    id: str
    cron: str
    prompt: str
    created_at: int
    recurring: bool = False
    agent_id: Optional[str] = None


class StateManager:
    """全局状态单例，参考 KAIROS state.ts"""
    
    _instance: Optional['StateManager'] = None
    
    def __init__(self):
        self.session_id: str = str(uuid.uuid4())[:8]
        self.parent_session_id: Optional[str] = None
        self.kairos_active: bool = False
        self.user_opt_in: bool = False
        self.cwd: str = os.getcwd()
        self.original_cwd: str = os.getcwd()
        self.start_time: datetime = datetime.now()
        self.last_interaction: datetime = datetime.now()
        
        # SessionCronTasks (内存, ephemeral)
        self.session_cron_tasks: List[SessionCronTask] = []
        
        # invokedSkills (compaction 保护)
        self.invoked_skills: Dict[str, SkillInfo] = {}
        
        # scheduledTasksEnabled
        self.scheduled_tasks_enabled: bool = False
        
        # isRemoteMode
        self.is_remote_mode: bool = False
        
        # tick count
        self.tick_count: int = 0
        
        # Signal callbacks
        self._session_switch_callbacks: List[Callable] = []
        
        # tick hooks
        self._tick_hooks: List[Callable] = []
        
        # PID file path
        self.pid_file: Optional[Path] = None
    
    @classmethod
    def get_instance(cls) -> 'StateManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls):
        """重置单例（用于测试或重启）"""
        cls._instance = None
    
    # ---- Session 管理 ----
    
    def switch_session(self, new_session_id: str):
        """切换会话，触发所有 Signal 回调"""
        old = self.session_id
        self.session_id = new_session_id
        for cb in self._session_switch_callbacks:
            try:
                cb(old, new_session_id)
            except Exception as e:
                print(f"[StateManager] session switch callback error: {e}")
    
    def regenerate_session_id(self):
        """重新生成会话 ID"""
        self.switch_session(str(uuid.uuid4())[:8])
    
    def on_session_switch(self, callback: Callable):
        """注册会话切换回调"""
        self._session_switch_callbacks.append(callback)
    
    # ---- Tick hooks ----
    
    def on_tick(self, callback: Callable):
        """注册心跳回调"""
        self._tick_hooks.append(callback)
    
    def fire_tick(self, context: Dict[str, Any]):
        """触发所有心跳回调"""
        self.tick_count += 1
        self.last_interaction = datetime.now()
        for hook in self._tick_hooks:
            try:
                hook(self.tick_count, context)
            except Exception as e:
                print(f"[StateManager] tick hook error: {e}")
    
    # ---- SessionCronTasks 管理 ----
    
    def add_session_cron_task(self, cron: str, prompt: str, 
                               agent_id: Optional[str] = None,
                               recurring: bool = True) -> str:
        """添加内存态 Cron 任务"""
        task = SessionCronTask(
            id=str(uuid.uuid4())[:8],
            cron=cron,
            prompt=prompt,
            created_at=int(datetime.now().timestamp()),
            recurring=recurring,
            agent_id=agent_id
        )
        self.session_cron_tasks.append(task)
        return task.id
    
    def remove_session_cron_task(self, task_id: str) -> bool:
        """移除内存态 Cron 任务"""
        for i, t in enumerate(self.session_cron_tasks):
            if t.id == task_id:
                self.session_cron_tasks.pop(i)
                return True
        return False
    
    def get_session_cron_tasks(self) -> List[SessionCronTask]:
        """获取所有内存态 Cron 任务"""
        return self.session_cron_tasks.copy()
    
    # ---- invokedSkills 管理 ----
    
    def set_invoked_skill(self, skill_name: str, skill_path: str,
                          content: str, agent_id: Optional[str] = None) -> str:
        """记录已调用的技能（跨 compaction 保留）"""
        key = f"{agent_id or ''}:{skill_name}"
        self.invoked_skills[key] = SkillInfo(
            skill_name=skill_name,
            skill_path=skill_path,
            content=content,
            invoked_at=datetime.now().isoformat(),
            agent_id=agent_id
        )
        return key
    
    def get_invoked_skill(self, skill_name: str, 
                          agent_id: Optional[str] = None) -> Optional[SkillInfo]:
        """获取已调用的技能"""
        key = f"{agent_id or ''}:{skill_name}"
        return self.invoked_skills.get(key)
    
    def clear_invoked_skills(self, agent_id: Optional[str] = None,
                              preserved_ids: Optional[set] = None):
        """清理技能记录（compaction 时调用）"""
        if agent_id is None and preserved_ids is None:
            self.invoked_skills.clear()
        else:
            keys_to_delete = []
            for key, skill in self.invoked_skills.items():
                if skill.agent_id == agent_id:
                    if preserved_ids is None or skill.skill_name not in preserved_ids:
                        keys_to_delete.append(key)
            for key in keys_to_delete:
                del self.invoked_skills[key]
    
    # ---- PID 文件管理 ----
    
    def write_pid_file(self, pid_file: Path):
        """写入 PID 文件（用于外部检测）"""
        self.pid_file = pid_file
        pid_file.write_text(str(os.getpid()), encoding='utf-8')
    
    def remove_pid_file(self):
        """删除 PID 文件"""
        if self.pid_file and self.pid_file.exists():
            self.pid_file.unlink()
    
    # ---- 持久化 ----
    
    def to_dict(self) -> Dict:
        """序列化（仅包含需要持久化的字段）"""
        return {
            'session_id': self.session_id,
            'parent_session_id': self.parent_session_id,
            'kairos_active': self.kairos_active,
            'user_opt_in': self.user_opt_in,
            'cwd': self.cwd,
            'original_cwd': self.original_cwd,
            'start_time': self.start_time.isoformat(),
            'last_interaction': self.last_interaction.isoformat(),
            'tick_count': self.tick_count,
            'is_remote_mode': self.is_remote_mode,
            'scheduled_tasks_enabled': self.scheduled_tasks_enabled,
            # session_cron_tasks 是内存态，不持久化
            # invoked_skills 由 SkillInvoker 单独管理
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'StateManager':
        """反序列化"""
        state = cls.get_instance()
        state.session_id = data.get('session_id', state.session_id)
        state.parent_session_id = data.get('parent_session_id')
        state.kairos_active = data.get('kairos_active', False)
        state.user_opt_in = data.get('user_opt_in', False)
        state.cwd = data.get('cwd', os.getcwd())
        state.original_cwd = data.get('original_cwd', os.getcwd())
        state.tick_count = data.get('tick_count', 0)
        state.is_remote_mode = data.get('is_remote_mode', False)
        state.scheduled_tasks_enabled = data.get('scheduled_tasks_enabled', False)
        
        if 'start_time' in data:
            state.start_time = datetime.fromisoformat(data['start_time'])
        if 'last_interaction' in data:
            state.last_interaction = datetime.fromisoformat(data['last_interaction'])
        
        return state
    
    def save_to_file(self, path: Path):
        """保存状态到文件"""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
    
    @classmethod
    def load_from_file(cls, path: Path) -> 'StateManager':
        """从文件加载状态"""
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return cls.from_dict(json.load(f))
        return cls.get_instance()
