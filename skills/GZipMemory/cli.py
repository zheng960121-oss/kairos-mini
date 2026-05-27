#!/usr/bin/env python3
"""GZipMemory CLI - standalone execution entry for cron jobs."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from archiver import ArchiveResult, MemoryArchiver, SearchResult, StatsResult

# Logging configuration
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"archive_{datetime.now(tz=timezone.utc).strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def cmd_archive(args: argparse.Namespace) -> ArchiveResult:
    """Archive command."""
    archiver = MemoryArchiver(base_dir=args.base_dir)

    logger.info(f"Starting archive, logs older than {args.days} days...")

    result = archiver.archive_old_logs(days=args.days, dry_run=args.dry_run)

    if args.dry_run:
        logger.info(f"[dry-run] Will archive {result['archived_count']} files")
    else:
        logger.info(
            f"Archive complete: {result['archived_count']} files, "
            f"original {result['archived_size_original']} bytes -> "
            f"compressed {result['archived_size_compressed']} bytes "
            f"({result['compression_ratio']})",
        )

        if result["errors"]:
            logger.warning(f"Partial failures: {result['errors']}")

    return result


def cmd_search(args: argparse.Namespace) -> list[SearchResult]:
    """Search command."""
    archiver = MemoryArchiver(base_dir=args.base_dir)

    logger.info(f"Searching archive: {args.query}")

    results = archiver.search(query=args.query, year=args.year, days=args.days)

    for _r in results:
        pass

    return results


def cmd_stats(args: argparse.Namespace) -> StatsResult:
    """Stats command."""
    archiver = MemoryArchiver(base_dir=args.base_dir)

    return archiver.get_stats()




def cmd_read(args: argparse.Namespace) -> str | None:
    """Read command for specified date."""
    archiver = MemoryArchiver(base_dir=args.base_dir)

    content = archiver.read_date(args.date)

    if content:
        pass
    else:
        pass

    return content


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GZipMemory - Memory Archiving Skill",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s archive --days 30        # Archive logs older than 30 days
  %(prog)s archive --days 30 --dry-run  # Dry run mode
  %(prog)s search "project" --year 2026  # Search archive
  %(prog)s stats                      # View stats
  %(prog)s read 2026-03-28           # Read specified date
        """,
    )

    parser.add_argument(
        "--base-dir",
        default="~/.openclaw/workspace",
        help="Working directory (default: ~/.openclaw/workspace)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # archive command
    p_archive = subparsers.add_parser("archive", help="Archive old logs")
    p_archive.add_argument(
        "--days",
        type=int,
        default=30,
        help="Days threshold (default: 30)",
    )
    p_archive.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode, do not actually execute",
    )
    p_archive.set_defaults(func=cmd_archive)

    # search command
    p_search = subparsers.add_parser("search", help="Search archive")
    p_search.add_argument("query", help="Search keyword")
    p_search.add_argument("--year", type=int, help="Specific year")
    p_search.add_argument("--days", type=int, help="Search within last N days")
    p_search.set_defaults(func=cmd_search)

    # stats command
    p_stats = subparsers.add_parser("stats", help="View stats")
    p_stats.set_defaults(func=cmd_stats)

    # read command
    p_read = subparsers.add_parser("read", help="Read log for specified date")
    p_read.add_argument("date", help="Date (YYYY-MM-DD)")
    p_read.set_defaults(func=cmd_read)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except Exception:
        logger.exception("Execution failed")
        raise


if __name__ == "__main__":
    main()
