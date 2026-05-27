"""search_core.py - unified search core logic for search_memory.py and search_tool.py."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Load archiver module (compatible with both import styles)
MODULE_PATH = Path(__file__).parent / "archiver.py"
spec = importlib.util.spec_from_file_location("archiver_module", MODULE_PATH)
archiver_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archiver_module)
MemoryArchiver = archiver_module.MemoryArchiver


def _search_recent_logs(
    archiver: MemoryArchiver, query: str, days: int,
) -> list[dict[str, Any]]:
    """Search recent logs (unarchived files in memory/ directory).

    Args:
        archiver: MemoryArchiver instance.
        query: Search keyword.
        days: Search range (days).

    Returns:
        List of recent log results.

    """
    results: list[dict[str, Any]] = []
    memory_dir: Path = archiver.memory_dir
    cutoff: datetime = datetime.now(tz=timezone.utc) - timedelta(days=min(days, 30))

    for log_file in memory_dir.glob("????-??-??.md"):
        date_str: str = log_file.stem
        try:
            file_date: datetime = datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc,
            )
            if file_date >= cutoff:
                content: str = log_file.read_text(encoding="utf-8")
                if query.lower() in content.lower():
                    results.append(
                        {
                            "date": date_str,
                            "content": content,
                            "source": f"memory/{log_file.name}",
                        },
                    )
        except ValueError:
            continue

    return results


def _format_search_results(  # noqa: PLR0913
    recent_results: list[dict[str, Any]],
    archive_results: list[dict[str, Any]],
    memory_md_content: str | None,
    query: str,
    days: int,
    max_content_len: int = 500,
) -> str:
    """Format search results into readable text."""
    total: int = len(recent_results) + len(archive_results) + (1 if memory_md_content else 0)
    output: list[str] = []
    output.append(f"Search for '{query}', found {total} results in {days} days:\n")

    # MEMORY.md results
    if memory_md_content:
        output.append("MEMORY.md (matched)\n")

    # Recent logs
    if recent_results:
        output.append("\nRecent logs")
        for r in recent_results:
            output.append(f"\n### {r['date']} ###")
            output.append(r["content"][:max_content_len])
            output.append("\n")

    # Archived logs
    if archive_results:
        output.append("\nArchived logs")
        for r in archive_results:
            output.append(f"\n### {r['date']} (archive) ###")
            output.append(r["content"][:max_content_len])
            output.append("\n")

    return "\n".join(output)
