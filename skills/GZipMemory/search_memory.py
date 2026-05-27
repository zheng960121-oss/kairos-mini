#!/usr/bin/env python3
"""search_memory.py - 统一搜索入口
集成 agent 的 memory_search 功能,自动扩展到 archive.

Usage:
    python3 search_memory.py "搜索关键词" [天数]

Example:
    python3 search_memory.py "小卡" 60
    python3 search_memory.py "项目进展" 30

"""

import sys
from typing import TYPE_CHECKING

from search_core import MemoryArchiver, _search_recent_logs

if TYPE_CHECKING:
    from pathlib import Path


def search_memory(query: str, days: int = 30) -> dict:
    """统一搜索入口
    1. 搜索 MEMORY.md
    2. 搜索 memory/*.md (近期)
    3. 搜索 memory/archive/*.gz (旧日志,超过30天时).
    """
    archiver = MemoryArchiver()

    # 1. 搜索 MEMORY.md
    memory_md_content: str | None = None
    memory_md_path: Path = archiver.memory_file
    if memory_md_path.exists():
        content: str = memory_md_path.read_text(encoding="utf-8")
        if query.lower() in content.lower():
            memory_md_content = content

    # 2. 搜索近期日志(memory/ 目录)
    recent_logs = _search_recent_logs(archiver, query, days)

    # 3. 搜索 archive(已归档的都是30天前的)
    archive_results = archiver.search(query=query)

    total: int = (1 if memory_md_content else 0) + len(recent_logs) + len(archive_results)

    return {
        "query": query,
        "days": days,
        "memory_md": [memory_md_content] if memory_md_content else [],
        "recent_logs": recent_logs,
        "archived_logs": archive_results,
        "total": total,
    }


if __name__ == "__main__":
    MIN_ARGS: int = 2
    if len(sys.argv) < MIN_ARGS:
        sys.exit(1)

    query = sys.argv[1]
    DEFAULT_DAYS: int = 30
    days = int(sys.argv[2]) if len(sys.argv) > MIN_ARGS else DEFAULT_DAYS

    results = search_memory(query, days)
    memory_md_content = results["memory_md"][0] if results["memory_md"] else None

    if results["total"] == 0:
        pass
    else:
        pass
