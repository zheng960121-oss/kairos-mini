"""
GZipMemory 搜索工具
集成到 agent 的 memory_search，当需要搜索旧日志时自动扩展到 archive
"""

import sys
from pathlib import Path
from typing import Dict, Any

sys.path.insert(0, str(Path(__file__).parent))

from archiver import MemoryArchiver

from search_core import _search_recent_logs


def gz_search(query: str, days: int = 30) -> Dict[str, Any]:
    """
    搜索记忆（包含 archive 扩展）

    当 days > 30 或普通搜索结果不足时，自动搜索 archive

    Args:
        query: 搜索关键词
        days: 搜索范围（默认30天）

    Returns:
        {
            "recent_results": [...],   # 近期日志结果
            "archive_results": [...],   # 归档日志结果
            "total": int,
            "searched_archive": bool
        }
    """
    archiver = MemoryArchiver()
    results: Dict[str, Any] = {
        "recent_results": [],
        "archive_results": [],
        "total": 0,
        "searched_archive": False
    }

    # 1. 搜索近期日志（memory/ 目录）
    results["recent_results"] = _search_recent_logs(archiver, query, days)

    # 2. 如果需要搜旧日志（days > 30），搜索 archive
    if days > 30:
        archive_results = archiver.search(query=query, days=days)
        results["archive_results"] = archive_results
        results["searched_archive"] = True

    results["total"] = len(results["recent_results"]) + len(results["archive_results"])

    return results


def gz_read_date(date_str: str) -> str:
    """
    读取指定日期的日志（自动检测 archive）

    Args:
        date_str: YYYY-MM-DD 格式

    Returns:
        日志内容，不存在返回空字符串
    """
    archiver = MemoryArchiver()
    content = archiver.read_date(date_str)
    return content if content else ""


def gz_stats() -> Dict[str, Any]:
    """获取统计信息"""
    archiver = MemoryArchiver()
    return archiver.get_stats()


def gz_archive(days: int = 30, dry_run: bool = False) -> Dict[str, Any]:
    """
    执行归档

    Args:
        days: 超过多少天归档（默认30天）
        dry_run: 演练模式

    Returns:
        归档报告
    """
    archiver = MemoryArchiver()
    return archiver.archive_old_logs(days=days, dry_run=dry_run)


if __name__ == "__main__":
    # 命令行测试
    import argparse

    parser = argparse.ArgumentParser(description="GZipMemory 搜索工具")
    parser.add_argument("action", choices=["search", "read", "stats", "archive"])
    parser.add_argument("--query", help="搜索关键词")
    parser.add_argument("--days", type=int, default=30, help="天数")
    parser.add_argument("--date", help="日期 (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.action == "search":
        result = gz_search(args.query, args.days)
        total, arch = result["total"], result["searched_archive"]
        print(f"找到 {total} 条结果 (搜索 archive: {arch})")
        for r in result["recent_results"]:
            print(f"\n### {r['date']} (recent) ###")
            print(r['content'][:300])
        for r in result["archive_results"]:
            print(f"\n### {r['date']} (archive) ###")
            print(r['content'][:300])

    elif args.action == "read":
        print(gz_read_date(args.date))

    elif args.action == "stats":
        print(gz_stats())

    elif args.action == "archive":
        print(gz_archive(args.days, args.dry_run))
