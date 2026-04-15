#!/usr/bin/env python3
"""
KAIROS-mini 2.0 - 单进程常驻模型
参考 KAIROS state.ts + memdir.ts + cron scheduler

启动方式:
    python main.py                    # 前台运行
    python main.py --daemon           # 后台运行
    python main.py --stop             # 停止后台进程
    python main.py --dashboard        # 启动并打开 Web Dashboard
    python main.py --run-once         # 单次执行（测试用）

设计要点:
- 单进程 + Signal/atexit 管理生命周期（无 watchdog）
- Cron 表达式调度（不只是固定 interval）
- Append-only daily log 记忆系统
- 文件锁保护并发
- Web Dashboard (http://localhost:8080)
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
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# 导入核心模块
from StateManager import StateManager, SessionCronTask
from MemDir import MemDir
from CronTab import CronTab
from Notifier import Notifier
from SkillInvoker import SkillInvoker
from OpenClawIntegration import OpenClawIntegration
from web_dashboard import DashboardServer, DashboardData


class KAIROSmini:
    """
    KAIROS-mini 2.0 主类
    整合所有模块，单进程常驻
    """
    
    def __init__(self, workspace: Path, tick_interval: int = 900,
                 kairos_active: bool = True, user_opt_in: bool = False):
        self.workspace = Path(workspace)
        self.tick_interval = tick_interval  # 使用传入的参数值
        
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
        
        # Dashboard
        self._dashboard_server: Optional[DashboardServer] = None
        
        # 注册 Signal 处理
        self._register_signals()
        
        # 注册清理
        atexit.register(self._cleanup)
    
    # ---- 生命周期管理 ----
    
    def acquire_lock(self) -> bool:
        """获取文件锁（防止多实例）"""
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        
        # ---- Fix #6: 清理残留锁文件 ----
        # 如果锁文件存在，先检查 PID 是否还活着
        if self.lock_file.exists():
            try:
                lock_content = self.lock_file.read_text().strip()
                if lock_content:
                    old_pid = int(lock_content)
                    # 检查 PID 是否存活
                    try:
                        os.kill(old_pid, 0)  # signal 0 只是检查进程是否存在
                    except OSError:
                        # 进程已死，删除残留锁文件
                        print(f"[KAIROS-mini] 清理残留锁文件 (stale PID: {old_pid})")
                        self.lock_file.unlink()
            except (ValueError, FileNotFoundError):
                # 无效内容，删除残留锁文件
                self.lock_file.unlink()
        
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
        
        # 停止 Dashboard
        if self._dashboard_server:
            try:
                self._dashboard_server.stop()
            except Exception:
                pass
        
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
    
    def start(self, dashboard_port: int = None, open_browser_dashboard: bool = False) -> bool:
        """启动 KAIROS-mini"""
        # 检查锁（如果已经获取过就跳过）
        if self._lock_fd is None and not self.acquire_lock():
            print(f"[KAIROS-mini] 无法获取锁，可能已有实例在运行")
            return False
        
        # 写入 PID 文件
        self.state.write_pid_file(self.pid_file)
        
        self._running = True
        print(f"[KAIROS-mini] 启动！Session: {self.state.session_id}")
        print(f"[KAIROS-mini] Workspace: {self.workspace}")
        print(f"[KAIROS-mini] Tick Interval: {self.tick_interval}s")
        print(f"[KAIROS-mini] CronTab tasks file: {self.crontab.tasks_file}")
        
        # 启动 Web Dashboard
        if dashboard_port:
            self._start_dashboard(dashboard_port, open_browser_dashboard)
        
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
        
        if self._dashboard_server:
            self._dashboard_server.stop()
        
        print(f"[KAIROS-mini] 已停止")
        sys.exit(0)
    
    # ---- Web Dashboard ----
    
    def _start_dashboard(self, port: int = 8080, open_browser: bool = False):
        """启动 Web Dashboard"""
        self._dashboard_data = DashboardData()
        self._dashboard_data.update(kairos=self, state=self.state, memdir=self.memdir)
        self._dashboard_server = DashboardServer(port=port, data=self._dashboard_data)
        self._dashboard_server.start(kairos=self)
        print(f"[KAIROS-mini] 🌐 Dashboard 启动: http://localhost:{port}/")
    
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
        """强制心跳 + 执行待处理任务"""
        self.state.tick_count += 1
        self.state.last_interaction = datetime.now()
        
        # 构建上下文
        context = self._build_context()
        
        # 更新 heartbeat
        self._update_heartbeat()
        
        # 执行待处理任务（每次tick都检查）
        self._execute_pending_tasks()
        
        # 触发所有 tick hooks
        self.state.fire_tick(context)
        
        # ---- Fix #1: 持久化状态到磁盘 ----
        # 每 3 个 tick 保存一次状态（避免频繁IO）
        if self.state.tick_count % 3 == 0:
            self._persist_state()
        
        # 记录到记忆
        if self.state.tick_count % 10 == 0:  # 每 10 次 tick 记录一次
            self.memdir.append_memory(
                f"心跳 #{self.state.tick_count} | 最后交互: {self.state.last_interaction.strftime('%H:%M')}",
                "heartbeat"
            )
    
    def _execute_pending_tasks(self):
        """执行待处理的任务"""
        try:
            # 延迟导入避免循环依赖
            from tasks import get_task_queue
            tq = get_task_queue()
            tq.refresh()  # 从文件重新加载，确保获取其他进程添加的任务
            pending = tq.get_pending_tasks()

            if pending:
                print(f"[KAIROS-mini] 发现 {len(pending)} 个待处理任务，开始执行...")
                # 使用 process_all() 统一处理，避免 execute_next() 与 pending 快照不匹配的问题
                results = tq.process_all()
                for task_id, success, msg in results:
                    print(f"[KAIROS-mini] 任务 {task_id} {'✅' if success else '❌'} {str(msg)[:100]}")
        except Exception as e:
            print(f"[KAIROS-mini] 执行任务失败: {e}")
    
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
        task_id = task.get('id', '')
        task_name = task.get('name', '')
        prompt = task.get('prompt', '')
        
        print(f"[KAIROS-mini] 执行任务: {task_id} - {prompt[:50]}...")
        
        # 根据任务类型路由
        if task_name in ('write_chapter', 'novel_chapter', 'ai_task', 'claude_task'):
            # 使用本地模型执行AI任务
            self._execute_ai_task(task)
            return
        elif prompt:
            # 追加到记忆（作为待处理事项）
            self.memdir.append_memory(
                f"[Cron Task] {prompt}",
                "task"
            )
    
    def _execute_ai_task(self, task: Dict):
        """使用本地模型执行AI任务（Claude Code + Ollama）"""
        try:
            from task_handlers import get_ollama_executor
            
            executor = get_ollama_executor()
            task_name = task.get('name', '')
            prompt = task.get('prompt', '')
            metadata = task.get('metadata', {})
            
            print(f"[KAIROS-mini] 使用本地模型执行: {executor.model}")
            
            # 写小说章节
            if task_name in ('write_chapter', 'novel_chapter'):
                chapter_num = metadata.get('chapter_num', 1)
                outline_file = metadata.get('outline_file', '')
                output_file = metadata.get('output_file', '')
                novel_path = metadata.get('novel_path', '')
                
                result = executor.execute(
                    prompt=f"""你是一个专业的玄幻小说作家。请根据以下要求写小说章节：

{prompt}

写作要求：
- 字数：3500-4000字
- 风格：热血燃系，节奏快
- 人物：林寒（主角，时间血脉）、周蛮（好兄弟）、苏幼微（女主）
- 格式：每个段落之间空一行，章节结尾用"**（第{chapter_num}章完）**"
- 直接输出正文，不要任何解释

请开始写作：""",
                    task_name=f"第{chapter_num}章",
                    output_file=output_file if output_file else None,
                    timeout=600
                )
            else:
                # 通用AI任务
                result = executor.execute(
                    prompt=prompt,
                    task_name=task_name,
                    timeout=300
                )
            
            if result['success']:
                output = result.get('stdout', '执行成功')
                if result.get('output_file'):
                    output += f"\n已保存到: {result['output_file']}"
                self.memdir.append_memory(
                    f"[AI Task Completed] {task_name}: {output[:200]}",
                    "task_result"
                )
                print(f"[KAIROS-mini] ✅ AI任务完成")
            else:
                error = result.get('error', '未知错误')
                self.memdir.append_memory(
                    f"[AI Task Failed] {task_name}: {error}",
                    "task_error"
                )
                print(f"[KAIROS-mini] ❌ AI任务失败: {error}")
                
        except Exception as e:
            print(f"[KAIROS-mini] ❌ AI任务执行异常: {e}")
            self.memdir.append_memory(
                f"[AI Task Error] {task.get('name', '')}: {str(e)}",
                "task_error"
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
    
    def _persist_state(self):
        """---- Fix #1: 持久化状态到磁盘 ----"""
        try:
            state_file = self.workspace / ".kairos" / "state.json"
            self.state.save_to_file(state_file)
            # 也保存 crontab 任务
            tasks_file = self.workspace / ".kairos" / "scheduled_tasks.json"
            self.crontab.save_tasks_to_file(tasks_file)
        except Exception as e:
            print(f"[KAIROS-mini] 状态持久化失败: {e}")
    
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
    parser.add_argument('--dashboard', action='store_true',
                       help='启动 Web Dashboard')
    parser.add_argument('--dashboard-port', type=int, default=8080,
                       help='Dashboard 端口 (默认: 8080)')
    parser.add_argument('--open-browser', action='store_true',
                       help='启动后自动打开浏览器')
    
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
    dashboard_port = args.dashboard_port if args.dashboard else None
    if kairos.start(dashboard_port=dashboard_port, open_browser_dashboard=args.open_browser):
        print("[KAIROS-mini] 运行中，按 Ctrl+C 停止")
        try:
            # 主线程等待
            while kairos._running:
                time.sleep(1)
        except KeyboardInterrupt:
            kairos.stop()


if __name__ == "__main__":
    main()
