"""
search_core.py - 统一搜索核心逻辑
search_memory.py 和 search_tool.py 的公共部分
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import importlib.util

# 加载 archiver 模块（兼容两种导入方式）
MODULE_PATH = Path(__file__).parent / "archiver.py"
spec = importlib.util.spec_from_file_location("archiver_module", MODULE_PATH)
archiver_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archiver_module)
MemoryArchiver = archiver_module.MemoryArchiver


def _search_recent_logs(archiver: MemoryArchiver, query: str, days: int) -> List[Dict[str, Any]]:
    """
    搜索近期日志（memory/ 目录中未归档的文件）

    Args:
        archiver: MemoryArchiver 实例
        query: 搜索关键词
        days: 搜索范围（天）

    Returns:
        近期日志结果列表
    """
    results: List[Dict[str, Any]] = []
    memory_dir: Path = archiver.memory_dir
    cutoff: datetime = datetime.now() - timedelta(days=min(days, 30))

    for log_file in memory_dir.glob("????-??-??.md"):
        date_str: str = log_file.stem
        try:
            file_date: datetime = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date >= cutoff:
                content: str = log_file.read_text(encoding="utf-8")
                if query.lower() in content.lower():
                    results.append({
                        "date": date_str,
                        "content": content,
                        "source": f"memory/{log_file.name}"
                    })
        except ValueError:
            continue

    return results


def _format_search_results(
    recent_results: List[Dict[str, Any]],
    archive_results: List[Dict[str, Any]],
    memory_md_content: str | None,
    query: str,
    days: int,
    max_content_len: int = 500,
) -> str:
    """格式化搜索结果为可读文本"""
    total: int = len(recent_results) + len(archive_results) + (1 if memory_md_content else 0)
    output: List[str] = []
    output.append(f"🔍 搜索「{query}」，{days}天内找到 {total} 条结果：\n")

    # MEMORY.md 结果
    if memory_md_content:
        output.append("📌 **MEMORY.md**")
        output.append("（匹配）\n")

    # 近期日志
    if recent_results:
        output.append("\n📅 **近期日志**")
        for r in recent_results:
            output.append(f"\n### {r['date']} ###")
            output.append(r['content'][:max_content_len])
            output.append("\n")

    # 归档日志
    if archive_results:
        output.append("\n📦 **归档日志**")
        for r in archive_results:
            output.append(f"\n### {r['date']} (archive) ###")
            output.append(r['content'][:max_content_len])
            output.append("\n")

    return "\n".join(output)
