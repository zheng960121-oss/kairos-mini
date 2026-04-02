"""
Logger - 统一日志系统
支持文件滚动日志、控制台输出、日志级别控制
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime

# 日志目录
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 日志文件
LOG_FILE = LOG_DIR / "kairos-mini.log"
ERROR_LOG_FILE = LOG_DIR / "errors.log"

# 日志级别环境变量或默认 INFO
LOG_LEVEL = logging.INFO

# 单例
_logger = None


class KairosFormatter(logging.Formatter):
    """自定义格式器，带颜色支持"""

    RESET = "\033[0m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    BLUE = "\033[94m"
    GRAY = "\033[90m"

    FORMATS = {
        logging.DEBUG:    GRAY + "[%(asctime)s] [%(name)s] [DBG] %(message)s" + RESET,
        logging.INFO:     GREEN + "[%(asctime)s] [%(name)s] [INF] %(message)s" + RESET,
        logging.WARNING:  YELLOW + "[%(asctime)s] [%(name)s] [WRN] %(message)s" + RESET,
        logging.ERROR:    RED + "[%(asctime)s] [%(name)s] [ERR] %(message)s" + RESET,
        logging.CITICAL: RED + "[%(asctime)s] [%(name)s] [CRT] %(message)s" + RESET,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno, "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s")
        formatter = logging.Formatter(
            log_fmt,
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        return formatter.format(record)


def get_logger(name: str = "kairos-mini") -> logging.Logger:
    """获取日志记录器（单例）"""
    global _logger

    if _logger is not None:
        return _logger

    _logger = logging.getLogger(name)
    _logger.setLevel(LOG_LEVEL)
    _logger.handlers.clear()

    # 避免重复添加 handler
    if not _logger.handlers:
        # 控制台输出
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(LOG_LEVEL)
        console.setFormatter(KairosFormatter())
        _logger.addHandler(console)

        # 文件滚动日志（最大 5MB，保留 3 个备份）
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setLevel(LOG_LEVEL)
        file_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        _logger.addHandler(file_handler)

        # 错误日志单独记录
        error_handler = RotatingFileHandler(
            ERROR_LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s\n%(pathname)s:%(lineno)d",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        _logger.addHandler(error_handler)

    return _logger


def log_heartbeat(tick_count: int, tick_time: datetime, extra: str = ""):
    """记录心跳日志"""
    logger = get_logger()
    logger.info(f"❤ 心跳 #{tick_count} @ {tick_time.strftime('%H:%M:%S')} {extra}")


def log_task(name: str, success: bool, msg: str = ""):
    """记录任务执行日志"""
    logger = get_logger()
    status = "✓" if success else "✗"
    logger.info(f"任务 [{name}] {status} {msg}")
