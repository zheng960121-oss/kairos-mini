#!/usr/bin/env python3
"""
KAIROS-mini 2.0 - 单进程常驻模型
参考 KAIROS state.ts + memdir.ts + cron scheduler

启动方式:
    python main.py                    # 前台运行
    python main.py --daemon           # 后台运行
    python main.py --stop             # 停止后台进程

设计要点:
- 单进程 + Signal/atexit 管理生命周期（无 watchdog）
- Cron 表达式调度（不只是固定 interval）
- Append-only daily log 记忆系统
- 文件锁保护并发
"""

import os
import sys
import signal
import atexit
import time
import argparse
import json
import fcntl
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# 导入核心模块
from StateManager import StateManager, SessionCronTask
from MemDir import MemDir
from CronTab import CronTab
from Notifier import Notifier
from SkillInvoker import SkillInvoker
from OpenClawIntegration import OpenClawIntegration


class KAIROSmini:
    """
    KAIROS-mini 2.0 主类
    整合所有模块，单进程常驻
    """
    
    def __init__(self, workspace: Path, tick_interval: int = 300,
                 kairos_active: bool = True, user_opt_in: bool = False):
        self.workspace = Path(workspace)
        self.tick_interval = tick_interval  # fallback tick interval (秒)
        
        # 初始化 StateManager
        self.state = StateManager.get_instance()
        self.state.kairos_active = kairos_active
        self.state.user_opt_in = user_opt_in
        
        # 初始化核心组件
        self.memdir = MemDir(self.workspace)
        self.notifier = Notifier(
            queue_file=self.workspace / ".kairos" / "notification_queue.json",
            heartbeat_file=self.workspace / "HEARTBEAT.md"
        )
        self.skill_invoker = SkillInvoker(self.state)
        self.openclaw = OpenClawIntegration(self.workspace)
        
        # 初始化 CronTab
        tasks_file = self.workspace / ".kairos" / "scheduled_tasks.json"
        self.crontab = CronTab(tasks_file, self.state.session_cron_tasks)
        
        # 文件锁
        self.lock_file = self.workspace / ".kairos" / "kairos.lock"
        self._lock_fd: Optional[int] = None
        
        # PID 文件
        self.pid_file = self.workspace / ".kairos" / "kairos.pid"
        
        # 运行状态
        self._running = False
        self._tick_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # 注册 Signal 处理
        self._register_signals()
        
        # 注册清理
        atexit.register(self._cleanup)
    
    # ---- 生命周期管理 ----
    
    def acquire_lock(self) -> bool:
        """获取文件锁（防止多实例）"""
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock_fd = os.open(self.lock_file, os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # 写入 PID
            os.write(self._lock_fd, str(os.getpid()).encode())
            return True
        except (IOError, OSError):
            if self._lock_fd:
                os.close(self._lock_fd)
                self._lock_fd = None
            return False
    
    def _register_signals(self):
        """注册 Signal 处理"""
        signal.signal(signal.SIGTERM, self._on_sigterm)
        signal.signal(signal.SIGINT, self._on_sigint)
        signal.signal(signal.SIGHUP, self._on_sighup)
    
    def _on_sigterm(self, signum, frame):
        """SIGTERM 处理（优雅退出）"""
        print(f"[KAIROS-mini] 收到 SIGTERM，准备退出...")
        self.stop()
    
    def _on_sigint(self, signum, frame):
        """SIGINT 处理（Ctrl+C）"""
        print(f"[KAIROS-mini] 收到 SIGINT，准备退出...")
        self.stop()
    
    def _on_sighup(self, signum, frame):
        """SIGHUP 处理（重载配置）"""
        print(f"[KAIROS-mini] 收到 SIGHUP，重载配置...")
        self._reload()
    
    def _reload(self):
        """重载配置"""
        config_file = self.workspace / ".kairos" / "config.json"
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text())
                self.tick_interval = config.get('tick_interval', self.tick_interval)
            except json.JSONDecodeError:
                pass
    
    def _cleanup(self):
        """清理资源"""
        print(f"[KAIROS-mini] 清理资源...")
        self._stop_event.set()
        
        # 关闭文件锁
        if self._lock_fd:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except:
                pass
        
        # 删除 PID 文件
        if self.pid_file.exists():
            try:
                self.pid_file.unlink()
            except:
                pass
        
        # 删除锁文件
        if self.lock_file.exists():
            try:
                self.lock_file.unlink()
            except:
                pass
        
        # 保存状态
        try:
            self.state.save_to_file(self.workspace / ".kairos" / "state.json")
        except:
            pass
    
    # ---- 启动/停止 ----
    
    def start(self) -> bool:
        """启动 KAIROS-mini"""
        # 检查锁
        if not self.acquire_lock():
            print(f"[KAIROS-mini] 无法获取锁，可能已有实例在运行")
            return False
        
        # 写入 PID 文件
        self.state.write_pid_file(self.pid_file)
        
        self._running = True
        print(f"[KAIROS-mini] 启动！Session: {self.state.session_id}")
        print(f"[KAIROS-mini] Workspace: {self.workspace}")
        print(f"[KAIROS-mini] Tick Interval: {self.tick_interval}s")
        print(f"[KAIROS-mini] CronTab tasks file: {self.crontab.tasks_file}")
        
        # 记录启动
        self.memdir.append_memory(
            f"KAIROS-mini 2.0 启动 | Session: {self.state.session_id}",
            "system"
        )
        
        # 启动 tick 线程
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()
        
        # 启动后执行一次
        self.run_once()
        
        return True
    
    def stop(self):
        """停止 KAIROS-mini"""
        print(f"[KAIROS-mini] 停止中...")
        self._running = False
        self._stop_event.set()
        
        if self._tick_thread and self._tick_thread.is_alive():
            self._tick_thread.join(timeout=5)
        
        print(f"[KAIROS-mini] 已停止")
        sys.exit(0)
    
    # ---- Tick 引擎 ----
    
    def _tick_loop(self):
        """Tick 主循环（在独立线程中运行）"""
        last_fallback_tick = time.time()
        
        while self._running and not self._stop_event.is_set():
            now = time.time()
            
            # 检查 cron 任务
            due_tasks = self.crontab.get_due_tasks()
            for task in due_tasks:
                self._execute_task(task)
                # 标记任务已执行
                self.crontab.mark_task_run(task['id'])
            
            # Fallback: 如果很久没执行，强制 tick
            if now - last_fallback_tick >= self.tick_interval:
                self._fallback_tick()
                last_fallback_tick = now
            
            # 等待下次检查（1 分钟）
            self._stop_event.wait(timeout=60)
    
    def run_once(self):
        """单次执行（用于测试或手动触发）"""
        self._fallback_tick()
    
    def _fallback_tick(self):
        """强制心跳"""
        self.state.tick_count += 1
        self.state.last_interaction = datetime.now()
        
        # 构建上下文
        context = self._build_context()
        
        # 更新 heartbeat
        self._update_heartbeat()
        
        # 触发所有 tick hooks
        self.state.fire_tick(context)
        
        # 记录到记忆
        if self.state.tick_count % 10 == 0:  # 每 10 次 tick 记录一次
            self.memdir.append_memory(
                f"心跳 #{self.state.tick_count} | 最后交互: {self.state.last_interaction.strftime('%H:%M')}",
                "heartbeat"
            )
    
    def _build_context(self) -> Dict[str, Any]:
        """构建 tick 上下文"""
        uptime = (datetime.now() - self.state.start_time).total_seconds()
        
        return {
            "state": self.state,
            "tick_count": self.state.tick_count,
            "uptime_seconds": uptime,
            "memory": self.memdir,
            "notifier": self.notifier,
            "skill_invoker": self.skill_invoker,
            "openclaw": self.openclaw,
            "crontab": self.crontab,
        }
    
    def _execute_task(self, task: Dict):
        """执行到期任务"""
        print(f"[KAIROS-mini] 执行任务: {task.get('id')} - {task.get('prompt', '')[:50]}...")
        
        # TODO: 根据 agent_id 路由到对应 agent
        # 目前直接在主进程执行
        prompt = task.get('prompt', '')
        
        if prompt:
            # 追加到记忆（作为待处理事项）
            self.memdir.append_memory(
                f"[Cron Task] {prompt}",
                "task"
            )
    
    def _update_heartbeat(self):
        """更新 heartbeat 文件"""
        uptime = (datetime.now() - self.state.start_time).total_seconds()
        
        items = [
            f"kairos-mini 心跳 #{self.state.tick_count}",
            f"运行时间: {int(uptime)}s",
            f"Session: {self.state.session_id}",
            f"内存任务数: {len(self.state.session_cron_tasks)}",
            f"文件任务数: {len(self.crontab.get_file_tasks())}",
        ]
        
        self.openclaw.write_heartbeat(items, title="KAIROS-mini Status")
    
    # ---- 命令行接口 ----
    
    def add_cron_task(self, cron_expr: str, prompt: str,
                      agent_id: Optional[str] = None,
                      recurring: bool = True) -> str:
        """添加 Cron 任务"""
        task_id = self.state.add_session_cron_task(
            cron=cron_expr,
            prompt=prompt,
            agent_id=agent_id,
            recurring=recurring
        )
        print(f"[KAIROS-mini] 添加任务: {task_id} ({cron_expr})")
        return task_id
    
    def add_file_task(self, cron_expr: str, prompt: str) -> str:
        """添加持久化任务"""
        task = {
            'cron': cron_expr,
            'prompt': prompt,
            'created_at': datetime.now().isoformat()
        }
        return self.crontab.add_file_task(task)
    
    def list_tasks(self) -> Dict[str, List]:
        """列出所有任务"""
        return {
            'memory': [
                {'id': t.id, 'cron': t.cron, 'prompt': t.prompt}
                for t in self.state.session_cron_tasks
            ],
            'file': self.crontab.get_file_tasks()
        }


# ---- 命令行入口 ----

def daemonize():
    """守护进程化（可选）"""
    # 简单实现：fork 一次
    try:
        pid = os.fork()
        if pid > 0:
            # 父进程退出
            print(f"[KAIROS-mini] 后台进程 PID: {pid}")
            sys.exit(0)
    except OSError as e:
        print(f"[KAIROS-mini] fork 失败: {e}")
        sys.exit(1)
    
    # 子进程
    os.chdir("/")
    os.setsid()
    os.umask(0)


def main():
    parser = argparse.ArgumentParser(description="KAIROS-mini 2.0")
    parser.add_argument('--workspace', '-w', type=str, default='.',
                       help='工作目录 (默认: 当前目录)')
    parser.add_argument('--tick-interval', '-t', type=int, default=300,
                       help='Fallback tick 间隔秒数 (默认: 300)')
    parser.add_argument('--daemon', '-d', action='store_true',
                       help='后台运行')
    parser.add_argument('--stop', action='store_true',
                       help='停止后台进程')
    parser.add_argument('--kairos-active', '-k', action='store_true', default=True,
                       help='KAIROS 模式激活')
    parser.add_argument('--no-kairos', action='store_true',
                       help='禁用 KAIROS 模式')
    parser.add_argument('--add-task', type=str, metavar='CRON:PROMPT',
                       help='添加 cron 任务 (格式: CRON:PROMPT, 如 "*/5 * * * *:检查邮件")')
    parser.add_argument('--list-tasks', action='store_true',
                       help='列出所有任务')
    parser.add_argument('--run-once', action='store_true',
                       help='运行一次后退出（测试用）')
    
    args = parser.parse_args()
    
    # 工作目录
    workspace = Path(args.workspace).expanduser().resolve()
    
    # 停止后台进程
    if args.stop:
        pid_file = workspace / ".kairos" / "kairos.pid"
        if pid_file.exists():
            pid = int(pid_file.read_text())
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"[KAIROS-mini] 已发送 SIGTERM 到 PID {pid}")
            except ProcessLookupError:
                print(f"[KAIROS-mini] 进程 {pid} 不存在")
                pid_file.unlink()
        else:
            print(f"[KAIROS-mini] PID 文件不存在")
        return
    
    # 后台运行
    if args.daemon:
        daemonize()
    
    # 创建实例
    kairos = KAIROSmini(
        workspace=workspace,
        tick_interval=args.tick_interval,
        kairos_active=not args.no_kairos,
        user_opt_in=False
    )
    
    # 添加任务
    if args.add_task:
        parts = args.add_task.split(':', 1)
        if len(parts) == 2:
            cron_expr, prompt = parts
            kairos.add_file_task(cron_expr, prompt)
        else:
            print("[KAIROS-mini] 错误: 任务格式应为 CRON:PROMPT")
            return
    
    # 列出任务
    if args.list_tasks:
        tasks = kairos.list_tasks()
        print("内存任务:")
        for t in tasks['memory']:
            print(f"  {t['id']}: {t['cron']} - {t['prompt']}")
        print("文件任务:")
        for t in tasks['file']:
            print(f"  {t['id']}: {t['cron']} - {t.get('prompt', '')}")
        return
    
    # 启动
    if args.run_once:
        kairos.start()
        kairos.run_once()
        print("[KAIROS-mini] 单次执行完成")
        return
    
    # 正常启动
    if kairos.start():
        print("[KAIROS-mini] 运行中，按 Ctrl+C 停止")
        try:
            # 主线程等待
            while kairos._running:
                time.sleep(1)
        except KeyboardInterrupt:
            kairos.stop()


if __name__ == "__main__":
    main()
