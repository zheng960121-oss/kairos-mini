"""MemoryArchiver - memory archiving module.

Archiving strategy: logs older than 30 days -> gzip -> memory/archive/YYYY/
Safe deletion: copy to archive first, then delete original after verification.
"""

from __future__ import annotations

import fcntl
import gzip
import io
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypedDict

Year = int
Days = int
Query = str


class ArchiveResult(TypedDict):
    """Result of an archiving operation."""

    archived_count: int
    archived_size_original: int
    archived_size_compressed: int
    compression_ratio: str
    cutoff_days: int
    skipped: list[str]
    errors: list[str]


class SearchResult(TypedDict):
    """Result of a search operation."""

    date: str
    content: str
    file_path: str


class StatsResult(TypedDict):
    """Statistics of logs and archives."""

    normal_logs: dict[str, int]
    archived_logs: dict[str, int]
    total_size_bytes: int
    compression_saved: int
    archive_dir: str


class MemoryArchiver:
    """Memory log archiver."""

    DEFAULT_THRESHOLD_DAYS: int = 30
    COMPRESS_SUFFIX: str = ".gz"

    def __init__(self, base_dir: str = "~/.openclaw/workspace") -> None:
        self.base_dir: Path = Path(base_dir).expanduser()
        self.memory_dir: Path = self.base_dir / "memory"
        self.archive_dir: Path = self.memory_dir / "archive"
        self.memory_file: Path = self.base_dir / "MEMORY.md"
        self._compiled_pattern: re.Pattern[str] | None = None

        # Ensure directories exist
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    # ---- Archiving core ----

    def archive_old_logs(
        self,
        days: int | None = None,
        dry_run: bool = False,  # noqa: FBT001,FBT002
    ) -> ArchiveResult:
        """Archive logs older than the specified number of days.

        Args:
            days: Number of days threshold (default 30).
            dry_run: If True, only report without executing.

        Returns:
            Archiving report.

        """
        days_val: int = days if days is not None else self.DEFAULT_THRESHOLD_DAYS
        cutoff: datetime = datetime.now(tz=timezone.utc) - timedelta(days=days_val)

        archived_count: int = 0
        archived_size_original: int = 0
        archived_size_compressed: int = 0
        errors: list[str] = []
        skipped: list[str] = []

        # Iterate all date files in memory directory
        for log_file in self._list_log_files():
            try:
                # Extract date from filename
                date_str: str = log_file.stem  # YYYY-MM-DD
                file_date: datetime = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc,
                )

                if file_date >= cutoff:
                    continue  # Within threshold, skip

                # Check if already in archive
                archive_path: Path = self._get_archive_path(log_file)
                if archive_path.exists():
                    skipped.append(str(log_file.name))
                    continue

                # Calculate original size
                original_size: int = log_file.stat().st_size

                if dry_run:
                    archived_count += 1
                    archived_size_original += original_size
                    continue

                # Safe delete: copy to archive, then delete original
                success: bool = self._safe_archive(log_file)
                if success:
                    archived_count += 1
                    archived_size_original += original_size
                    compressed_size: int = archive_path.stat().st_size
                    archived_size_compressed += compressed_size
                else:
                    errors.append(f"Failed to archive {log_file.name}")

            except ValueError:
                # Non-date format file, skip
                continue
            except OSError as e:
                errors.append(f"{log_file.name}: {e!s}")

        ratio_str: str
        if archived_size_compressed > 0 and archived_size_original > 0:
            ratio: float = (1 - archived_size_compressed / archived_size_original) * 100
            ratio_str = f"{ratio:.1f}%"
        else:
            ratio_str = "N/A"

        result: ArchiveResult = {
            "archived_count": archived_count,
            "archived_size_original": archived_size_original,
            "archived_size_compressed": archived_size_compressed,
            "compression_ratio": ratio_str,
            "cutoff_days": days_val,
            "skipped": skipped,
            "errors": errors,
        }

        if archived_count > 0 and not dry_run:
            pass

        return result

    def _safe_archive(self, log_file: Path) -> bool:
        """Safe archiving: copy first, delete after.

        1. Acquire file lock (prevent concurrent archiving).
        2. Compress to temp file.
        3. Move to archive directory.
        4. Verify file integrity.
        5. Delete original file.
        """
        archive_path: Path = self._get_archive_path(log_file)
        temp_path: Path | None = None
        lock_path: Path = self.memory_dir / ".archive.lock"
        lock_fd: int | None = None
        try:
            # 1. Acquire file lock
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            try:
                # Check if already in archive (after locking)
                if archive_path.exists():
                    return True

                # 2. Compress
                year_dir: Path = archive_path.parent
                year_dir.mkdir(parents=True, exist_ok=True)

                compressed_data: bytes = self._compress_file(log_file)

                # 3. Write to archive (temp file first, then rename)
                temp_path = archive_path.with_suffix(".tmp")
                temp_path.write_bytes(compressed_data)

                # 4. Verify: re-read to check integrity
                with gzip.open(temp_path, "rt", encoding="utf-8") as f:
                    f.read()

                # 5. Verified: atomic rename then delete original
                temp_path.rename(archive_path)
                temp_path = None  # Avoid finally cleanup
                log_file.unlink()

                return True

            finally:
                # Release file lock (nested try ensures lock always released)
                if lock_fd is not None:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
                    lock_fd = None

        except (OSError, gzip.BadGzipFile):
            # Cleanup temp file on failure
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
            raise

        finally:
            # Final safety cleanup
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
                except OSError:
                    pass

    def _compress_file(self, file_path: Path) -> bytes:
        """Compress file content to gzip using streaming."""
        buffer = io.BytesIO()
        with file_path.open("rb") as f_in, gzip.GzipFile(
            fileobj=buffer, mode="wb",
        ) as gz_out:
            while True:
                chunk = f_in.read(65536)
                if not chunk:
                    break
                gz_out.write(chunk)
        return buffer.getvalue()

    def _get_archive_path(self, log_file: Path) -> Path:
        """Get archive destination path."""
        year: str = log_file.stem[:4]  # Extract year from YYYY-MM-DD
        return self.archive_dir / year / f"{log_file.stem}.md{self.COMPRESS_SUFFIX}"

    def _list_log_files(self) -> list[Path]:
        """List all log files."""
        pattern: str = "????-??-??.md"
        return sorted(self.memory_dir.glob(pattern))

    def _is_valid_date_file(self, gz_file: Path, cutoff: datetime) -> bool:
        """Check if a gz file date is within cutoff (helper to avoid PERF203)."""
        try:
            date_str = gz_file.with_suffix("").stem
            file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc,
            )
        except ValueError:
            return False
        else:
            return file_date >= cutoff

    # ---- Search core ----

    def search(
        self,
        query: Query,
        year: Year | None = None,
        days: Days | None = None,
    ) -> list[SearchResult]:
        """Search archived logs.

        Args:
            query: Search keyword.
            year: Specific year (optional).
            days: Search within last N days (optional).

        Returns:
            List of search results with date, content, file_path.

        """
        results: list[SearchResult] = []

        if year is not None:
            year_dir: Path = self.archive_dir / str(year)
            if not year_dir.exists():
                return results
            archive_files: list[Path] = list(
                year_dir.rglob(f"*.md{self.COMPRESS_SUFFIX}"),
            )
        elif days is not None:
            cutoff: datetime = datetime.now(tz=timezone.utc) - timedelta(days=days)
            archive_files = [
                gz_file
                for gz_file in self.archive_dir.rglob(f"*.md{self.COMPRESS_SUFFIX}")
                if self._is_valid_date_file(gz_file, cutoff)
            ]

        else:
            archive_files = list(self.archive_dir.rglob(f"*.md{self.COMPRESS_SUFFIX}"))

        for gz_file in archive_files:
            try:
                content: str = self.read_compressed(gz_file)
            except (OSError, ValueError):
                continue

            if query.lower() in content.lower():
                date_key = gz_file.with_suffix("").stem
                results.append(
                    {
                        "date": date_key,
                        "content": content,
                        "file_path": str(gz_file),
                    },
                )

        return results

    def search_grep(
        self,
        pattern: str,
        year: Year | None = None,
    ) -> list[SearchResult]:
        """Regex search (using zgrep, faster).

        Args:
            pattern: Regular expression.
            year: Specific year (optional).

        """
        results: list[SearchResult] = []

        if not self.archive_dir.exists():
            return results

        # Validate and sanitize pattern to prevent injection
        try:
            re.compile(pattern)
        except re.error:
            return results  # Invalid regex, return empty

        # Check for shell metacharacters (simple approach)
        _sh = frozenset(['`', '|', ';', '$', '&'])
        if _sh.intersection(pattern):
            return results  # Contains dangerous chars, return empty

        cmd: list[str] = ["zgrep", "-H", "-E", pattern]
        if year is not None:
            year_dir: Path = self.archive_dir / str(year)
            if not year_dir.exists():
                return results
            gz_files: list[Path] = list(year_dir.rglob(f"*.md{self.COMPRESS_SUFFIX}"))
            cmd.extend([str(f) for f in gz_files])
        else:
            cmd.append(str(self.archive_dir))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.archive_dir,
                check=True,
            )

            current_file: str | None = None
            current_lines: list[str] = []

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                if ":" in line:
                    filename_part, matched_line = line.split(":", 1)
                    gz_file: Path = Path(filename_part.strip())

                    if current_file != str(gz_file):
                        if current_file is not None and current_lines:
                            date_str = Path(current_file).with_suffix("").stem
                            results.append(
                                {
                                    "file_path": current_file,
                                    "date": date_str,
                                    "content": "\n".join(current_lines),
                                },
                            )
                        current_file = str(gz_file)
                        current_lines = []

                    current_lines.append(matched_line.strip())

            if current_file is not None and current_lines:
                results.append(
                    {
                        "file_path": current_file,
                        "date": Path(current_file).with_suffix("").stem,
                        "content": "\n".join(current_lines),
                    },
                )

        except subprocess.CalledProcessError:
            pass  # zgrep returns 1 when no matches, which is normal

        return results

    def read_compressed(self, file_path: Path) -> str:
        """Read compressed file content."""
        try:
            with gzip.open(file_path, "rt", encoding="utf-8") as f:
                return f.read()
        except gzip.BadGzipFile:
            return ""

    def read_date(self, date_str: str) -> str | None:
        """Read log for specified date (auto-detect archive).

        Args:
            date_str: YYYY-MM-DD format.

        Returns:
            Log content, or None if not found.

        """
        normalized: str | None = None
        try:
            datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            normalized = date_str
        except ValueError:
            normalized = self._normalize_date(date_str)

        if normalized is None:
            return None

        date_str = normalized  # type: ignore[assignment]

        # Check normal directory first
        normal_path: Path = self.memory_dir / f"{date_str}.md"
        if normal_path.exists():
            return normal_path.read_text(encoding="utf-8")

        # Then check archive
        archive_path: Path = (
            self.archive_dir / date_str[:4] / f"{date_str}.md{self.COMPRESS_SUFFIX}"
        )
        if archive_path.exists():
            return self.read_compressed(archive_path)

        return None

    def _normalize_date(self, date_str: str) -> str | None:
        """Convert short date format to standard format, return None on failure."""
        DATE_PARTS_MAX: int = 3
        MONTH_MAX: int = 12
        DAY_MAX: int = 31
        try:
            parts: list[str] = date_str.split("-")
            if len(parts) != DATE_PARTS_MAX:
                return None
            year = int(parts[0])
            month = int(parts[1])
            day = int(parts[2])
            # Range check
            if not (1 <= month <= MONTH_MAX and 1 <= day <= DAY_MAX):
                return None
        except (ValueError, IndexError):
            return None
        else:
            return f"{year}-{month:02d}-{day:02d}"

    # ---- Stats ----

    def get_stats(self) -> StatsResult:
        """Get archiving statistics."""
        total_original: int = 0
        total_compressed: int = 0
        file_count_normal: int = 0
        file_count_archive: int = 0

        # Normal logs
        for f in self.memory_dir.glob("????-??-??.md"):
            total_original += f.stat().st_size
            file_count_normal += 1

        # Archived
        for f in self.archive_dir.rglob(f"*.md{self.COMPRESS_SUFFIX}"):
            total_compressed += f.stat().st_size
            file_count_archive += 1

        return {
            "normal_logs": {
                "count": file_count_normal,
                "size_bytes": total_original,
            },
            "archived_logs": {
                "count": file_count_archive,
                "size_bytes": total_compressed,
            },
            "total_size_bytes": total_original + total_compressed,
            "compression_saved": max(0, total_original - total_compressed),
            "archive_dir": str(self.archive_dir),
        }


# ---- Entry point ----

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Memory Archive CLI")
    parser.add_argument(
        "action",
        choices=["archive", "search", "stats", "read"],
    )
    parser.add_argument("--days", type=int, default=30, help="Days threshold")
    parser.add_argument("--query", help="Search keyword")
    parser.add_argument("--year", type=int, help="Specific year")
    parser.add_argument("--date", help="Specific date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")

    args = parser.parse_args()
    archiver = MemoryArchiver()

    if args.action == "archive":
        result = archiver.archive_old_logs(days=args.days, dry_run=args.dry_run)

    elif args.action == "search":
        results = archiver.search(query=args.query, year=args.year, days=args.days)
        for _r in results:
            pass

    elif args.action == "stats":
        pass

    elif args.action == "read":
        content = archiver.read_date(args.date)
