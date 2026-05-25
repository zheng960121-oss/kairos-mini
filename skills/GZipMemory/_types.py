"""
类型别名定义
"""

from typing import Dict, List, TypedDict


Year = int
Days = int
Query = str


class ArchiveResult(TypedDict):
    archived_count: int
    archived_size_original: int
    archived_size_compressed: int
    compression_ratio: str
    cutoff_days: int
    skipped: List[str]
    errors: List[str]


class SearchResult(TypedDict):
    date: str
    content: str
    file_path: str


class StatsResult(TypedDict):
    normal_logs: Dict[str, int]
    archived_logs: Dict[str, int]
    total_size_bytes: int
    compression_saved: int
    archive_dir: str
