#!/usr/bin/env python3
"""
GZipMemory CLI - 独立执行入口
用于 cron 定时任务调用
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from archiver import MemoryArchiver

# 日志配置
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"archive_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def cmd_archive(args):
    """归档命令"""
    archiver = MemoryArchiver(base_dir=args.base_dir)
    
    logger.info(f"开始归档，超过 {args.days} 天的日志...")
    
    result = archiver.archive_old_logs(days=args.days, dry_run=args.dry_run)
    
    if args.dry_run:
        logger.info(f"[dry-run] 将归档 {result['archived_count']} 个文件")
    else:
        logger.info(f"归档完成: {result['archived_count']} 个文件, "
                    f"原始 {result['archived_size_original']} bytes → "
                    f"压缩 {result['archived_size_compressed']} bytes "
                    f"({result['compression_ratio']})")
        
        if result['errors']:
            logger.warning(f"部分失败: {result['errors']}")
    
    return result


def cmd_search(args):
    """搜索命令"""
    archiver = MemoryArchiver(base_dir=args.base_dir)
    
    logger.info(f"搜索归档: {args.query}")
    
    results = archiver.search(query=args.query, year=args.year, days=args.days)
    
    print(f"\n找到 {len(results)} 条结果:\n")
    for r in results:
        print(f"### {r['date']} ###")
        print(r['content'][:500])
        print()
    
    return results


def cmd_stats(args):
    """统计命令"""
    archiver = MemoryArchiver(base_dir=args.base_dir)
    
    stats = archiver.get_stats()
    
    print("\n=== GZipMemory 统计 ===")
    print(f"普通日志: {stats['normal_logs']['count']} 个文件, "
          f"{stats['normal_logs']['size_bytes']:,} bytes")
    print(f"归档日志: {stats['archived_logs']['count']} 个文件, "
          f"{stats['archived_logs']['size_bytes']:,} bytes")
    print(f"压缩节省: {stats['compression_saved']:,} bytes")
    print(f"归档目录: {stats['archive_dir']}")
    
    return stats


def cmd_read(args):
    """读取指定日期日志"""
    archiver = MemoryArchiver(base_dir=args.base_dir)
    
    content = archiver.read_date(args.date)
    
    if content:
        print(content)
    else:
        print(f"未找到日期 {args.date} 的日志")
    
    return content


def main():
    parser = argparse.ArgumentParser(
        description="GZipMemory - 记忆归档技能",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s archive --days 30        # 归档30天前的日志
  %(prog)s archive --days 30 --dry-run  # 演练模式
  %(prog)s search "项目进展" --year 2026  # 搜索归档
  %(prog)s stats                      # 查看统计
  %(prog)s read 2026-03-28           # 读取指定日期
        """
    )
    
    parser.add_argument(
        "--base-dir",
        default="~/.openclaw/workspace",
        help="工作目录 (默认: ~/.openclaw/workspace)"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="子命令")
    
    # archive 命令
    p_archive = subparsers.add_parser("archive", help="归档旧日志")
    p_archive.add_argument(
        "--days", type=int, default=30, help="超过多少天归档 (默认: 30)"
    )
    p_archive.add_argument(
        "--dry-run", action="store_true", help="演练模式，不实际执行"
    )
    p_archive.set_defaults(func=cmd_archive)
    
    # search 命令
    p_search = subparsers.add_parser("search", help="搜索归档")
    p_search.add_argument("query", help="搜索关键词")
    p_search.add_argument("--year", type=int, help="指定年份")
    p_search.add_argument("--days", type=int, help="搜索最近N天")
    p_search.set_defaults(func=cmd_search)
    
    # stats 命令
    p_stats = subparsers.add_parser("stats", help="查看统计")
    p_stats.set_defaults(func=cmd_stats)
    
    # read 命令
    p_read = subparsers.add_parser("read", help="读取指定日期的日志")
    p_read.add_argument("date", help="日期 (YYYY-MM-DD)")
    p_read.set_defaults(func=cmd_read)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    try:
        args.func(args)
    except Exception as e:
        logger.error(f"执行失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
