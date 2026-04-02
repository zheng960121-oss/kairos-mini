"""
SkillInvoker - 技能调用器
参考 KAIROS invokedSkills
compaction 时保留 skill 内容
"""

from typing import Dict, Optional, Set, List, Any
from datetime import datetime
from pathlib import Path
import json

from StateManager import StateManager, SkillInfo


class SkillInvoker:
    """
    技能调用器 - 参考 KAIROS invokedSkills
    - invokedSkills Map 跨 compaction 保留
    - Agent 级别隔离
    - Skill 内容存储在 StateManager 中
    """
    
    def __init__(self, state: StateManager):
        self.state = state
        self._skill_cache: Dict[str, SkillInfo] = {}
    
    def invoke(self, skill_name: str, skill_path: str,
               content: str, agent_id: Optional[str] = None) -> str:
        """
        调用技能，内容存入 state（跨 compaction 保留）
        
        Args:
            skill_name: 技能名称
            skill_path: 技能文件路径
            content: 技能内容（可包含参数）
            agent_id: 指定 agent（可选）
        
        Returns:
            skill key
        """
        key = self.state.set_invoked_skill(
            skill_name=skill_name,
            skill_path=skill_path,
            content=content,
            agent_id=agent_id
        )
        
        # 也缓存一份到本地（快速访问）
        self._skill_cache[key] = self.state.get_invoked_skill(skill_name, agent_id)
        
        return key
    
    def get_skill(self, skill_name: str, 
                  agent_id: Optional[str] = None) -> Optional[SkillInfo]:
        """
        获取已调用的技能（compaction 恢复用）
        """
        # 先从本地缓存获取
        key = f"{agent_id or ''}:{skill_name}"
        if key in self._skill_cache:
            return self._skill_cache[key]
        
        # 再从 state 获取
        skill = self.state.get_invoked_skill(skill_name, agent_id)
        if skill:
            self._skill_cache[key] = skill
        
        return skill
    
    def get_skill_content(self, skill_name: str,
                          agent_id: Optional[str] = None) -> Optional[str]:
        """获取技能内容（简化接口）"""
        skill = self.get_skill(skill_name, agent_id)
        return skill.content if skill else None
    
    def has_skill(self, skill_name: str,
                  agent_id: Optional[str] = None) -> bool:
        """检查技能是否已调用"""
        return self.get_skill(skill_name, agent_id) is not None
    
    def list_skills(self, agent_id: Optional[str] = None) -> List[str]:
        """
        列出已调用的技能
        """
        skills = []
        prefix = f"{agent_id}:" if agent_id else ""
        
        for key in self.state.invoked_skills:
            if agent_id is None or key.startswith(prefix):
                # 提取 skill_name
                parts = key.split(":")
                if len(parts) >= 2:
                    skill_name = ":".join(parts[1:])  # skill name 可能包含冒号
                else:
                    skill_name = parts[0]
                skills.append(skill_name)
        
        return skills
    
    def list_all_skills(self) -> Dict[str, SkillInfo]:
        """列出所有技能（带详情）"""
        return self.state.invoked_skills.copy()
    
    # ---- Compaction 支持 ----
    
    def prepare_for_compaction(self, agent_id: str,
                                preserved_ids: Optional[Set[str]] = None) -> Dict[str, str]:
        """
        Compaction 前准备：保留需要保留的 skill 内容
        
        Returns:
            待恢复的 skill 内容字典 {skill_name: content}
        """
        preserved = {}
        
        for key, skill in self.state.invoked_skills.items():
            if skill.agent_id == agent_id:
                if preserved_ids is None or skill.skill_name in preserved_ids:
                    preserved[skill.skill_name] = skill.content
        
        return preserved
    
    def restore_after_compaction(self, preserved: Dict[str, str],
                                  agent_id: str):
        """
        Compaction 后恢复：重新注册保留的 skill
        """
        for skill_name, content in preserved.items():
            self.invoke(
                skill_name=skill_name,
                skill_path="",  # path 可能已失效
                content=content,
                agent_id=agent_id
            )
    
    def clear_for_agent(self, agent_id: str,
                         preserved_ids: Optional[Set[str]] = None):
        """
        清理 agent 的 skill 记录（compaction 时调用）
        """
        # 先获取保留的 skill
        preserved = self.prepare_for_compaction(agent_id, preserved_ids)
        
        # 清理 state 中的记录
        self.state.clear_invoked_skills(agent_id, preserved_ids)
        
        # 重建本地缓存
        self._skill_cache = {
            f"{agent_id}:{name}": SkillInfo(
                skill_name=name,
                skill_path="",
                content=content,
                invoked_at=datetime.now().isoformat(),
                agent_id=agent_id
            )
            for name, content in preserved.items()
        }
    
    # ---- Skill 持久化 ----
    
    def save_to_file(self, path: Path):
        """保存 skill 记录到文件"""
        data = {
            key: {
                'skill_name': skill.skill_name,
                'skill_path': skill.skill_path,
                'content': skill.content,
                'invoked_at': skill.invoked_at,
                'agent_id': skill.agent_id
            }
            for key, skill in self.state.invoked_skills.items()
        }
        
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), 
                        encoding="utf-8")
    
    def load_from_file(self, path: Path):
        """从文件加载 skill 记录"""
        if not path.exists():
            return
        
        data = json.loads(path.read_text(encoding="utf-8"))
        
        for key, info in data.items():
            skill = SkillInfo(**info)
            self.state.invoked_skills[key] = skill
            self._skill_cache[key] = skill
    
    # ---- 统计 ----
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total = len(self.state.invoked_skills)
        by_agent: Dict[str, int] = {}
        
        for key, skill in self.state.invoked_skills.items():
            agent_id = skill.agent_id or "global"
            by_agent[agent_id] = by_agent.get(agent_id, 0) + 1
        
        return {
            "total_skills": total,
            "by_agent": by_agent,
            "cache_size": len(self._skill_cache)
        }
