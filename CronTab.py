"""
CronTab - Cron 表达式调度器
参考 KAIROS sessionCronTasks 设计
支持 cron 表达式，不只是固定 interval
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any, Callable
from dataclasses import dataclass, asdict
import time


class CronTab:
    """
    Cron 调度器
    - 支持 cron 表达式（5段式）
    - 文件任务 + 内存任务统一调度
    - 精确按时执行
    """
    
    def __init__(self, tasks_file: Path, session_cron_tasks: List = None):
        self.tasks_file = Path(tasks_file)
        self.tasks_file.parent.mkdir(parents=True, exist_ok=True)
        self._session_cron_tasks = session_cron_tasks or []
        self._last_tick = datetime.now()
        self._tick_interval = 60  # 默认 60 秒检查一次
    
    @property
    def session_cron_tasks(self) -> List:
        return self._session_cron_tasks
    
    # ---- Cron 表达式解析 ----
    
    @staticmethod
    def parse_cron_field(field: str, min_val: int, max_val: int) -> List[int]:
        """解析单个 cron 字段"""
        values = []
        
        if field == '*':
            return list(range(min_val, max_val + 1))
        
        for part in field.split(','):
            if '/' in part:
                base, step = part.split('/')
                step = int(step)
                if base == '*':
                    base = min_val
                else:
                    base = int(base)
                values.extend(range(base, max_val + 1, step))
            elif '-' in part:
                start, end = part.split('-')
                values.extend(range(int(start), int(end) + 1))
            else:
                values.append(int(part))
        
        return sorted(set(values))
    
    @staticmethod
    def parse_cron_expr(cron_expr: str) -> Dict[str, List[int]]:
        """
        解析完整 cron 表达式（5段式）
        minute hour day month weekday
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expr: {cron_expr}")
        
        return {
            'minute': CronTab.parse_cron_field(parts[0], 0, 59),
            'hour': CronTab.parse_cron_field(parts[1], 0, 23),
            'day': CronTab.parse_cron_field(parts[2], 1, 31),
            'month': CronTab.parse_cron_field(parts[3], 1, 12),
            'weekday': CronTab.parse_cron_field(parts[4], 0, 6),
        }
    
    @staticmethod
    def cron_is_due(cron_expr: str, now: datetime = None) -> bool:
        """检查 cron 表达式是否在当前时刻到期"""
        if now is None:
            now = datetime.now()
        
        try:
            parsed = CronTab.parse_cron_expr(cron_expr)
        except ValueError:
            return False
        
        # 检查每个字段
        if now.minute not in parsed['minute']:
            return False
        if now.hour not in parsed['hour']:
            return False
        if now.day not in parsed['day']:
            return False
        if now.month not in parsed['month']:
            return False
        if now.weekday() not in parsed['weekday']:
            return False
        
        return True
    
    @staticmethod
    def get_next_run(cron_expr: str, from_time: datetime = None, 
                     max_iterations: int = 1000) -> Optional[datetime]:
        """计算下次执行时间"""
        if from_time is None:
            from_time = datetime.now()
        
        try:
            parsed = CronTab.parse_cron_expr(cron_expr)
        except ValueError:
            return None
        
        current = from_time.replace(second=0, microsecond=0)
        
        for _ in range(max_iterations):
            # 检查月
            if current.month not in parsed['month']:
                current = current.replace(day=1, hour=0, minute=0)
                # 下个月
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)
                continue
            
            # 检查日
            import calendar
            max_day = calendar.monthrange(current.year, current.month)[1]
            if current.day not in parsed['day'] or current.day > max_day:
                current = current.replace(day=1, hour=0, minute=0)
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)
                continue
            
            # 检查时
            if current.hour not in parsed['hour']:
                # 找下一个有效小时
                next_hour = min([h for h in parsed['hour'] if h > current.hour] or [parsed['hour'][0]])
                if next_hour <= current.hour:
                    # 下一天
                    current = current.replace(day=current.day + 1, hour=next_hour, minute=0)
                    if current.day > max_day:
                        current = current.replace(day=1, month=current.month + 1)
                else:
                    current = current.replace(hour=next_hour, minute=0)
                continue
            
            # 检查分
            if current.minute not in parsed['minute']:
                next_minute = min([m for m in parsed['minute'] if m > current.minute] or [parsed['minute'][0]])
                if next_minute <= current.minute:
                    current = current.replace(hour=current.hour + 1, minute=next_minute)
                else:
                    current = current.replace(minute=next_minute)
                continue
            
            # 检查 weekday
            if current.weekday() not in parsed['weekday']:
                current = current.replace(day=current.day + 1, hour=0, minute=0)
                continue
            
            return current
        
        return None
    
    # ---- 文件任务管理 ----
    
    def _read_file_tasks(self) -> List[Dict]:
        """从文件读取持久化任务"""
        if not self.tasks_file.exists():
            return []
        
        try:
            with open(self.tasks_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    
    def _write_file_tasks(self, tasks: List[Dict]):
        """写入持久化任务到文件"""
        with open(self.tasks_file, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, indent=2, ensure_ascii=False)
    
    def save_tasks_to_file(self, path: Path):
        """保存任务到指定路径（Fix #1）"""
        tasks = self._read_file_tasks()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, indent=2, ensure_ascii=False)
    
    def add_file_task(self, task: Dict) -> str:
        """添加文件任务"""
        tasks = self._read_file_tasks()
        task_id = task.get('id') or str(int(time.time() * 1000))
        task['id'] = task_id
        tasks.append(task)
        self._write_file_tasks(tasks)
        return task_id
    
    def remove_file_task(self, task_id: str) -> bool:
        """移除文件任务"""
        tasks = self._read_file_tasks()
        original_len = len(tasks)
        tasks = [t for t in tasks if t.get('id') != task_id]
        if len(tasks) < original_len:
            self._write_file_tasks(tasks)
            return True
        return False
    
    def get_file_tasks(self) -> List[Dict]:
        """获取所有文件任务"""
        return self._read_file_tasks()
    
    # ---- 调度检查 ----
    
    def get_due_tasks(self, now: datetime = None) -> List[Dict]:
        """
        返回所有到期任务（包括文件和内存的）
        """
        if now is None:
            now = datetime.now()
        
        due = []
        
        # 检查文件任务
        for task in self._read_file_tasks():
            if self._is_task_due(task, now):
                due.append(task.copy())
        
        # 检查 session 内存任务
        for task in self._session_cron_tasks:
            task_dict = {
                'id': task.id,
                'cron': task.cron,
                'prompt': task.prompt,
                'recurring': task.recurring,
                'agent_id': task.agent_id,
                'source': 'memory'
            }
            if self._is_task_due(task_dict, now):
                due.append(task_dict)
        
        return due
    
    def _is_task_due(self, task: Dict, now: datetime) -> bool:
        """检查单个任务是否到期"""
        cron_expr = task.get('cron')
        if not cron_expr:
            return False
        
        # 检查是否是 recurring 任务且刚执行过
        if task.get('last_run'):
            last_run = datetime.fromisoformat(task['last_run'])
            # 如果上次执行距离现在不到 2 分钟，跳过
            if (now - last_run).total_seconds() < 120:
                next_run = self.get_next_run(cron_expr, last_run)
                if next_run and next_run > now:
                    return False
        
        return self.cron_is_due(cron_expr, now)
    
    def mark_task_run(self, task_id: str, now: datetime = None):
        """标记任务已执行"""
        if now is None:
            now = datetime.now()
        
        # 更新文件任务
        tasks = self._read_file_tasks()
        for task in tasks:
            if task.get('id') == task_id:
                task['last_run'] = now.isoformat()
                self._write_file_tasks(tasks)
                return
        
        # 更新内存任务
        for task in self._session_cron_tasks:
            if task.id == task_id:
                # 更新 last_run 跟踪（内存任务不持久化）
                task.last_run = now  # type: ignore
                return
    
    # ---- 常用 Cron 表达式 ----
    
    @staticmethod
    def every_minute() -> str:
        return "* * * * *"
    
    @staticmethod
    def every_5_minutes() -> str:
        return "*/5 * * * *"
    
    @staticmethod
    def every_15_minutes() -> str:
        return "*/15 * * * *"
    
    @staticmethod
    def every_hour() -> str:
        return "0 * * * *"
    
    @staticmethod
    def daily_at(hour: int, minute: int = 0) -> str:
        return f"{minute} {hour} * * *"
    
    @staticmethod
    def weekly_on(weekday: int, hour: int = 0, minute: int = 0) -> str:
        """weekday: 0=周一, 6=周日"""
        return f"{minute} {hour} * * {weekday}"
    
    @staticmethod
    def monthly_on(day: int, hour: int = 0, minute: int = 0) -> str:
        """day: 1-31"""
        return f"{minute} {hour} {day} * *"
