"""
MemDir - Append-only daily log + distill
参考 KAIROS memdir.ts 设计
AI 可直接读写 Markdown 文件
"""

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
from collections import defaultdict


class MemDir:
    """
    记忆系统 - daily append log + 定期 distill
    替代原来的三层 JSON 存储
    """
    
    MEMORY_FILE = "MEMORY.md"
    ENTRYPOINT_LINES_MAX = 200
    
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.memory_dir = self.base_dir / "memory"
        self.log_dir = self.memory_dir / "logs"
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        """确保目录存在"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    # ---- Daily Log 路径 ----
    
    def today_log_path(self) -> Path:
        """今日日志文件路径：memory/logs/YYYY/MM/YYYY-MM-DD.md"""
        today = datetime.now()
        return self.log_dir / str(today.year) / f"{today.month:02d}" / f"{today.strftime('%Y-%m-%d')}.md"
    
    def log_path_for_date(self, date: datetime) -> Path:
        """指定日期的日志文件路径"""
        return self.log_dir / str(date.year) / f"{date.month:02d}" / f"{date.strftime('%Y-%m-%d')}.md"
    
    # ---- Append Memory ----
    
    def append_memory(self, content: str, memory_type: str = "general",
                      tags: Optional[List[str]] = None):
        """
        追加到今日日志（append-only）
        不重写任何已有内容
        """
        path = self.today_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        tags_str = ""
        if tags:
            tags_str = " ".join([f"#{t}" for t in tags])
        
        line = f"- [{timestamp}] [{memory_type}] {content}"
        if tags_str:
            line += f" {tags_str}"
        line += "\n"
        
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    
    def add_memory(self, content: str, memory_type: str = "general"):
        """add_memory 的别名（兼容旧接口）"""
        self.append_memory(content, memory_type)
    
    # ---- Read Memory ----
    
    def read_today_log(self) -> str:
        """读取今日日志"""
        path = self.today_log_path()
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""
    
    def read_log_for_date(self, date: datetime) -> str:
        """读取指定日期的日志"""
        path = self.log_path_for_date(date)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""
    
    def read_recent_logs(self, days: int = 7) -> Dict[datetime, str]:
        """读取最近 N 天的日志"""
        result = {}
        today = datetime.now()
        for i in range(days):
            date = today - timedelta(days=i)
            content = self.read_log_for_date(date)
            if content:
                result[date] = content
        return result
    
    # ---- MEMORY.md 管理 ----
    
    def memory_file_path(self) -> Path:
        """MEMORY.md 文件路径"""
        return self.memory_dir / self.MEMORY_FILE
    
    def read_memory_index(self) -> str:
        """读取 MEMORY.md 索引文件"""
        path = self.memory_file_path()
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""
    
    def append_to_memory_index(self, line: str):
        """追加一行到 MEMORY.md"""
        path = self.memory_file_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    
    def update_memory_index(self, lines: List[str]):
        """重写 MEMORY.md（distill 时调用）"""
        path = self.memory_file_path()
        # 保留前 N 行（防止无限增长）
        all_lines = lines[:self.ENTRYPOINT_LINES_MAX]
        content = "\n".join(all_lines) + "\n"
        path.write_text(content, encoding="utf-8")
    
    # ---- Distill ----
    
    def distill_nightly(self, days: int = 7) -> Dict[str, Any]:
        """
        夜间提炼：从 daily logs 提炼到 MEMORY.md
        由 cron 任务调用，每天执行一次
        
        Returns:
            distill report with stats
        """
        recent = self.read_recent_logs(days)
        
        # 按类型分组
        by_type: Dict[str, List[str]] = defaultdict(list)
        for date, content in recent.items():
            for line in content.strip().split("\n"):
                if not line.strip():
                    continue
                # 解析: - [timestamp] [type] content
                match = re.match(r"- \[([^\]]+)\] \[([^\]]+)\] (.+)", line)
                if match:
                    timestamp, mtype, text = match.groups()
                    by_type[mtype].append(text)
        
        # 去重
        unique_memories = []
        seen = set()
        for mtype, items in by_type.items():
            for item in items:
                # 简单去重（基于前50字符）
                key = item[:50].lower()
                if key not in seen:
                    seen.add(key)
                    unique_memories.append(f"- [{mtype}] {item}")
        
        # 更新 MEMORY.md
        self.update_memory_index(unique_memories)
        
        return {
            "days_processed": days,
            "unique_memories": len(unique_memories),
            "by_type": dict(by_type)
        }
    
    # ---- Build Memory Prompt ----
    
    def build_memory_prompt(self, max_lines: int = 100) -> str:
        """
        构造 AI 系统提示词用的记忆段落
        包含 MEMORY.md 内容
        """
        memory_index = self.read_memory_index()
        
        if not memory_index:
            return ""
        
        # 截断
        lines = memory_index.strip().split("\n")
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        
        header = "## 记忆上下文\n\n"
        body = "\n".join(lines)
        footer = "\n\n---\n*记忆时间有限，如需更多细节请搜索记忆日志*"
        
        return header + body + footer
    
    # ---- Search Memory ----
    
    def search_memory(self, query: str, days: int = 30) -> List[str]:
        """
        搜索记忆内容（供 AI 调用）
        简单 grep 风格搜索
        """

    def query_memories(self, query: str, days: int = 30) -> List[str]:
        """query_memories 的别名，保持向后兼容"""
        return self.search_memory(query, days)
        results = []
        recent = self.read_recent_logs(days)
        
        query_lower = query.lower()
        for date, content in recent.items():
            for line in content.strip().split("\n"):
                if query_lower in line.lower():
                    results.append(line)
        
        return results
    
    def search_memory_grep(self, pattern: str, days: int = 30) -> List[str]:
        """正则搜索记忆"""
        import re
        results = []
        recent = self.read_recent_logs(days)
        
        compiled = re.compile(pattern, re.IGNORECASE)
        for date, content in recent.items():
            for line in content.strip().split("\n"):
                if compiled.search(line):
                    results.append(line)
        
        return results
    
    # ---- 统计 ----
    
    def get_stats(self) -> Dict[str, Any]:
        """获取记忆统计"""
        total_entries = 0
        total_size = 0
        files = list(self.log_dir.rglob("*.md"))
        
        for f in files:
            content = f.read_text(encoding="utf-8")
            total_entries += len(content.strip().split("\n"))
            total_size += len(content.encode('utf-8'))
        
        return {
            "total_files": len(files),
            "total_entries": total_entries,
            "total_size_bytes": total_size,
            "memory_dir": str(self.memory_dir)
        }
