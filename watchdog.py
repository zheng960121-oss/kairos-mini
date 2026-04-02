#!/usr/bin/env python3
"""
Watchdog - 进程守护模块
监控主进程健康状态，异常退出后自动重启
"""

import sys
import time
import signal
import os
import atexit
from pathlib import Path
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from logger import get_logger

logger = get_logger("watchdog")

# PID 文件
PID_DIR = Path(__file__).parent / "run"
PID_DIR.mkdir(exist_ok=True)
MAIN_PID_FILE = PID_DIR / "kairos-main.pid"
WATCHDOG_PID_FILE = PID_DIR / "watchdog.pid"

# 健康检查
HEALTH_CHECK_INTERVAL = 60   # 每 60 秒检查一次
MAX_HEARTBEAT_AGE = 900       # 15 分钟没更新认为心跳死了
MAX_RESTART_INTERVAL = 60    # 最小重启间隔（秒），防止疯狂重启
MAX_CONSECUTIVE_FAILURES = 3  # 连续失败 N 次后报警

# 心跳文件（记录最后心跳时间）
HEARTBEAT_FILE = PID_DIR / "heartbeat.txt"


class Watchdog:
    """进程守护器"""

    def __init__(self):
        self.main_pid = None
        self.running = True
        self.consecutive_failures = 0
        self.last_restart_time = 0
        self.last_heartbeat = None

    def _write_pid(self):
        """写入 watchdog PID"""
        pid = os.getpid()
        WATCHDOG_PID_FILE.write_text(str(pid))
        logger.info(f"Watchdog PID: {pid}")

    def _read_main_pid(self) -> int:
        """读取主进程 PID"""
        try:
            return int(MAIN_PID_FILE.read_text().strip())
        except Exception:
            return None

    def _write_main_pid(self, pid: int):
        """写入主进程 PID"""
        MAIN_PID_FILE.write_text(str(pid))

    def _is_process_alive(self, pid: int) -> bool:
        """检查进程是否存活"""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _check_heartbeat(self) -> bool:
        """检查主进程心跳是否正常"""
        try:
            if not HEARTBEAT_FILE.exists():
                return False
            content = HEARTBEAT_FILE.read_text().strip()
            if not content:
                return False
            # 格式: PID|timestamp
            parts = content.split("|")
            if len(parts) != 2:
                return False
            hb_pid = int(parts[0])
            hb_time = float(parts[1])
            age = time.time() - hb_time
            return age < MAX_HEARTBEAT_AGE and self._is_process_alive(hb_pid)
        except Exception:
            return False

    def _start_main_process(self):
        """启动主进程"""
        pid = os.fork()
        if pid == 0:
            # 子进程：执行主程序
            os.setsid()  # 创建新会话
            os.execv(sys.executable, [sys.executable, str(Path(__file__).parent / "main.py"), "--watchdog-mode"])
        else:
            # 父进程：记录 PID
            self._write_main_pid(pid)
            logger.info(f"主进程已启动，PID: {pid}")
            return pid

    def _stop_main_process(self):
        """优雅停止主进程"""
        pid = self._read_main_pid()
        if pid and self._is_process_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                logger.info(f"已发送 SIGTERM 到主进程 {pid}")
                # 等待最多 10 秒
                for _ in range(20):
                    if not self._is_process_alive(pid):
                        break
                    time.sleep(0.5)
                else:
                    os.kill(pid, signal.SIGKILL)
                    logger.warning(f"主进程 {pid} 未响应 SIGTERM，强制 kill")
            except OSError as e:
                logger.error(f"停止主进程失败: {e}")

    def _restart_main_process(self):
        """重启主进程"""
        now = time.time()

        # 检查重启频率
        if now - self.last_restart_time < MAX_RESTART_INTERVAL:
            self.consecutive_failures += 1
            logger.warning(f"重启间隔太短 ({now - self.last_restart_time:.0f}s)，连续失败计数: {self.consecutive_failures}")
        else:
            self.consecutive_failures = 1

        self.last_restart_time = now

        # 连续失败报警
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            self._alert_failure()
            self.consecutive_failures = 0  # 重置计数

        logger.info(f"尝试重启主进程 (第 {self.consecutive_failures} 次连续失败后)...")

        # 先停止
        self._stop_main_process()
        time.sleep(2)

        # 再启动
        self._start_main_process()

    def _alert_failure(self):
        """连续失败后报警（写通知文件）"""
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from notifier import get_notifier
            n = get_notifier()
            n.alert(
                f"⚠️ KAIROS-mini 连续重启失败 {MAX_CONSECUTIVE_FAILURES} 次！"
                f"请检查日志: {Path(__file__).parent / 'logs' / 'errors.log'}"
            )
            logger.error(f"已发送连续失败报警（连续 {self.consecutive_failures} 次）")
        except Exception as e:
            logger.error(f"发送失败报警失败: {e}")

    def _cleanup(self):
        """清理资源"""
        logger.info("Watchdog 清理...")
        self._stop_main_process()
        if WATCHDOG_PID_FILE.exists():
            WATCHDOG_PID_FILE.unlink()

    def run(self):
        """运行守护循环"""
        self._write_pid()
        logger.info("=" * 50)
        logger.info("KAIROS-mini Watchdog 启动")
        logger.info(f"健康检查间隔: {HEALTH_CHECK_INTERVAL}s")
        logger.info(f"心跳超时: {MAX_HEARTBEAT_AGE}s")
        logger.info(f"连续失败报警阈值: {MAX_CONSECUTIVE_FAILURES}")
        logger.info("=" * 50)

        # 注册信号
        def signal_handler(sig, frame):
            logger.info(f"收到信号 {sig}，正在停止...")
            self.running = False

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGHUP, signal_handler)

        # 注册退出清理
        atexit.register(self._cleanup)

        # 启动主进程
        self._start_main_process()

        # 守护循环
        while self.running:
            time.sleep(HEALTH_CHECK_INTERVAL)

            if not self.running:
                break

            # 检查主进程是否存活
            main_pid = self._read_main_pid()
            if main_pid is None or not self._is_process_alive(main_pid):
                logger.warning(f"主进程 {main_pid} 已退出，重启中...")
                self._restart_main_process()
                continue

            # 检查心跳
            if not self._check_heartbeat():
                logger.warning("主进程心跳超时，可能已僵死，重启中...")
                self._restart_main_process()

        logger.info("Watchdog 已停止")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="KAIROS-mini Watchdog")
    parser.add_argument("--check", action="store_true", help="检查主进程状态")
    args = parser.parse_args()

    if args.check:
        wd = Watchdog()
        main_pid = wd._read_main_pid()
        if main_pid and wd._is_process_alive(main_pid):
            alive = wd._check_heartbeat()
            print(f"主进程 PID: {main_pid}")
            print(f"进程状态: {'存活' if wd._is_process_alive(main_pid) else '死亡'}")
            print(f"心跳状态: {'正常' if alive else '超时/异常'}")
            sys.exit(0 if alive else 1)
        else:
            print("主进程未运行")
            sys.exit(1)
    else:
        wd = Watchdog()
        wd.run()


if __name__ == "__main__":
    main()
