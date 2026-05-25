"""
GZipMemory - 内存日志压缩归档系统
"""

from .archiver import MemoryArchiver
from ._types import (
    ArchiveResult,
    SearchResult,
    StatsResult,
    Year,
    Days,
    Query,
)

__all__ = [
    "MemoryArchiver",
    "ArchiveResult",
    "SearchResult",
    "StatsResult",
    "Year",
    "Days",
    "Query",
]
