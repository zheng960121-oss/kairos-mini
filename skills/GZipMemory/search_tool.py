"""GZipMemory search tool.

Integrated with agent's memory_search, automatically extends to archive when needed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from archiver import MemoryArchiver
from search_core import _search_recent_logs


def gz_search(query: str, days: int = 30) -> dict[str, Any]:
    """Search memory (including archive extension).

    When days > 30 or normal search results are insufficient,
    automatically search archive.

    Args:
        query: Search keyword.
        days: Search range (default 30 days).

    Returns:
        {
            "recent_results": [...],   # Recent log results
            "archive_results": [...],  # Archived log results
            "total": int,
            "searched_archive": bool
        }

    """
    archiver = MemoryArchiver()
    results: dict[str, Any] = {
        "recent_results": [],
        "archive_results": [],
        "total": 0,
        "searched_archive": False,
    }

    # 1. Search recent logs (memory/ directory)
    results["recent_results"] = _search_recent_logs(archiver, query, days)

    # 2. If older logs needed (days > 30), search archive
    archive_threshold_days: int = 30
    if days > archive_threshold_days:
        archive_results = archiver.search(query=query, days=days)
        results["archive_results"] = archive_results
        results["searched_archive"] = True

    results["total"] = len(results["recent_results"]) + len(results["archive_results"])

    return results


def gz_read_date(date_str: str) -> str:
    """Read log for specified date (auto-detect archive).

    Args:
        date_str: YYYY-MM-DD format.

    Returns:
        Log content, empty string if not found.

    """
    archiver = MemoryArchiver()
    content = archiver.read_date(date_str)
    return content or ""


def gz_stats() -> dict[str, Any]:
    """Get statistics."""
    archiver = MemoryArchiver()
    return archiver.get_stats()


def gz_archive(days: int = 30, dry_run: bool = False) -> dict[str, Any]:  # noqa: FBT001,FBT002
    """Execute archiving.

    Args:
        days: Days threshold (default 30 days).
        dry_run: Dry run mode.

    Returns:
        Archiving report.

    """
    archiver = MemoryArchiver()
    return archiver.archive_old_logs(days=days, dry_run=dry_run)


if __name__ == "__main__":
    # CLI test
    import argparse

    parser = argparse.ArgumentParser(description="GZipMemory search tool")
    parser.add_argument("action", choices=["search", "read", "stats", "archive"])
    parser.add_argument("--query", help="Search keyword")
    parser.add_argument("--days", type=int, default=30, help="Days")
    parser.add_argument("--date", help="Date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.action == "search":
        result = gz_search(args.query, args.days)
        total = result["total"]
        arch = result["searched_archive"]
        for _r in result["recent_results"]:
            pass
        for _r in result["archive_results"]:
            pass

    elif args.action in {"read", "stats"} or args.action == "archive":
        pass
