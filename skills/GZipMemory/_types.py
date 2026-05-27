"""Type alias definitions."""

from typing import TypedDict


class ArchiveResult(TypedDict):
    archived_count: int
    archived_size_original: int
    archived_size_compressed: int
    compression_ratio: str
    cutoff_days: int
    skipped: list[str]
    errors: list[str]


class SearchResult(TypedDict):
    date: str
    content: str
    file_path: str


class StatsResult(TypedDict):
    normal_logs: dict[str, int]
    archived_logs: dict[str, int]
    total_size_bytes: int
    compression_saved: int
    archive_dir: str


Year = int
Days = int
Query = str
