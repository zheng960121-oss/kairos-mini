"""
MemoryArchiver - 记忆归档模块
归档策略：30天前的日志 → gzip压缩 → memory/archive/YYYY/
安全删除：先复制再删除原始文件
"""

from __future__ import annotations

import fcntl
import gzip
import io
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Pattern

# Inline types to avoid relative import issues
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


class MemoryArchiver:
    """记忆归档器"""

    DEFAULT_THRESHOLD_DAYS: int = 30
    COMPRESS_SUFFIX: str = ".gz"

    def __init__(self, base_dir: str = "~/.openclaw/workspace") -> None:
        self.base_dir: Path = Path(os.path.expanduser(base_dir))
        self.memory_dir: Path = self.base_dir / "memory"
        self.archive_dir: Path = self.memory_dir / "archive"
        self.memory_file: Path = self.base_dir / "MEMORY.md"
        self._compiled_pattern: Optional[Pattern[str]] = None

        # 确保目录存在
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    # ---- 归档核心 ----

    def archive_old_logs(
        self,
        days: Optional[int] = None,
        dry_run: bool = False,
    ) -> ArchiveResult:
        """
        归档超过指定天数的日志

        Args:
            days: 超过多少天归档（默认30天）
            dry_run: True则只报告不执行

        Returns:
            归档报告
        """
        days_val: int = days if days is not None else self.DEFAULT_THRESHOLD_DAYS
        cutoff: datetime = datetime.now() - timedelta(days=days_val)

        archived_count: int = 0
        archived_size_original: int = 0
        archived_size_compressed: int = 0
        errors: List[str] = []
        skipped: List[str] = []

        # 遍历 memory 目录下的所有日期文件
        for log_file in self._list_log_files():
            try:
                # 从文件名提取日期
                date_str: str = log_file.stem  # YYYY-MM-DD
                file_date: datetime = datetime.strptime(date_str, "%Y-%m-%d")

                if file_date >= cutoff:
                    continue  # 不超过阈值，跳过

                # 检查是否已经在 archive
                archive_path: Path = self._get_archive_path(log_file)
                if archive_path.exists():
                    skipped.append(str(log_file.name))
                    continue

                # 计算原始大小
                original_size: int = log_file.stat().st_size

                if dry_run:
                    archived_count += 1
                    archived_size_original += original_size
                    continue

                # 安全删除：先复制到 archive，成功后删除原文件
                success: bool = self._safe_archive(log_file, file_date)
                if success:
                    archived_count += 1
                    archived_size_original += original_size
                    compressed_size: int = archive_path.stat().st_size
                    archived_size_compressed += compressed_size
                else:
                    errors.append(f"Failed to archive {log_file.name}")

            except ValueError:
                # 非日期格式文件，跳过
                continue
            except Exception as e:
                errors.append(f"{log_file.name}: {str(e)}")

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
            print(
                f"[MemoryArchiver] 归档完成: {archived_count}个文件, "
                f"原始{archived_size_original} bytes "
                f"→ 压缩后{archived_size_compressed} bytes "
                f"({ratio_str})"
            )

        return result

    def _safe_archive(self, log_file: Path, file_date: datetime) -> bool:
        """
        安全归档：先复制再删除

        1. 获取文件锁（防止并发归档）
        2. 压缩到临时文件
        3. 移动到 archive 目录
        4. 验证文件完整性
        5. 删除原始文件
        """
        archive_path: Path = self._get_archive_path(log_file)
        temp_path: Optional[Path] = None
        lock_path: Path = self.memory_dir / ".archive.lock"
        lock_fd: Optional[int] = None
        try:
            # 1. 获取文件锁
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            # 再次检查是否已在 archive（加锁后）
            if archive_path.exists():
                return True

            # 2. 压缩
            year_dir: Path = archive_path.parent
            year_dir.mkdir(parents=True, exist_ok=True)

            compressed_data: bytes = self._compress_file(log_file)

            # 3. 写入 archive（先写临时文件再rename，更安全）
            temp_path = archive_path.with_suffix(".tmp")
            with open(temp_path, "wb") as f:
                f.write(compressed_data)
            temp_path.rename(archive_path)  # atomic rename

            # 4. 验证：重新读取检查完整性
            with gzip.open(archive_path, "rt", encoding="utf-8") as f:
                f.read()

            # 5. 验证成功，删除原始文件
            log_file.unlink()

            return True

        except Exception as e:
            # 失败时清理临时文件
            if temp_path is None:
                temp_path = archive_path.with_suffix(".tmp")
            if temp_path.exists():
                temp_path.unlink()
            raise e

        finally:
            # 释放文件锁
            if lock_fd is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)

    def _compress_file(self, file_path: Path) -> bytes:
        """将文件内容流式压缩为 gzip"""
        buffer = io.BytesIO()
        with open(file_path, "rb") as f_in:
            with gzip.GzipFile(fileobj=buffer, mode="wb") as gz_out:
                while True:
                    chunk = f_in.read(65536)
                    if not chunk:
                        break
                    gz_out.write(chunk)
        return buffer.getvalue()

    def _get_archive_path(self, log_file: Path) -> Path:
        """获取 archive 后的目标路径"""
        year: str = log_file.stem[:4]  # 从 YYYY-MM-DD 提取年份
        return self.archive_dir / year / f"{log_file.stem}.md{self.COMPRESS_SUFFIX}"

    def _list_log_files(self) -> List[Path]:
        """列出所有日志文件"""
        pattern: str = "????-??-??.md"
        return sorted(self.memory_dir.glob(pattern))

    # ---- 检索核心 ----

    def search(
        self,
        query: Query,
        year: Optional[Year] = None,
        days: Optional[Days] = None,
    ) -> List[SearchResult]:
        """
        搜索归档日志

        Args:
            query: 搜索关键词
            year: 指定年份（可选）
            days: 搜索最近N天的归档（可选）

        Returns:
            搜索结果列表，每项包含 date, content, file_path
        """
        results: List[SearchResult] = []

        if year is not None:
            # Bug7 fix: 使用 rglob 保持一致，并检查目录存在性
            year_dir: Path = self.archive_dir / str(year)
            if not year_dir.exists():
                return results
            archive_files: List[Path] = list(year_dir.rglob(f"*.md{self.COMPRESS_SUFFIX}"))
        elif days is not None:
            # 指定天数内的归档
            cutoff: datetime = datetime.now() - timedelta(days=days)
            archive_files = []
            for gz_file in self.archive_dir.rglob(f"*.md{self.COMPRESS_SUFFIX}"):
                try:
                    # with_suffix('').stem 正确提取日期：/archive/2026/2026-04-01.md.gz → 2026-04-01
                    date_str = gz_file.with_suffix("").stem
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                    if file_date >= cutoff:
                        archive_files.append(gz_file)
                except ValueError:
                    continue
        else:
            # 全部归档
            archive_files = list(
                self.archive_dir.rglob(f"*.md{self.COMPRESS_SUFFIX}")
            )

        for gz_file in archive_files:
            try:
                content: str = self.read_compressed(gz_file)
                if query.lower() in content.lower():
                    # with_suffix('').stem 正确提取日期
                    date_key = gz_file.with_suffix("").stem
                    results.append(
                        {
                            "date": date_key,
                            "content": content,
                            "file_path": str(gz_file),
                        }
                    )
            except Exception as e:
                print(f"[MemoryArchiver] 读取失败 {gz_file}: {e}")

        return results

    def search_grep(
        self,
        pattern: str,
        year: Optional[Year] = None,
    ) -> List[SearchResult]:
        """
        正则搜索（使用 zgrep，更快）

        Args:
            pattern: 正则表达式
            year: 指定年份（可选）
        """
        results: List[SearchResult] = []

        if not self.archive_dir.exists():
            return results

        cmd: List[str] = ["zgrep", "-H", "-E", pattern]
        if year is not None:
            # Bug1 & Bug7 fix: 检查目录存在性，使用 rglob 保持一致
            year_dir: Path = self.archive_dir / str(year)
            if not year_dir.exists():
                return results
            gz_files: List[Path] = list(year_dir.rglob(f"*.md{self.COMPRESS_SUFFIX}"))
            cmd.extend([str(f) for f in gz_files])
        else:
            cmd.append(str(self.archive_dir))


        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.archive_dir,
            )

            if result.returncode == 0:
                current_file: Optional[str] = None
                current_lines: List[str] = []

                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    # zgrep -H 输出格式: filename:matched_line
                    if ":" in line:
                        filename_part, matched_line = line.split(":", 1)
                        gz_file: Path = Path(filename_part.strip())

                        if current_file != str(gz_file):
                            # 保存上一个文件的结果
                            if current_file is not None and current_lines:
                                # prev_gz.with_suffix('').stem 正确提取日期
                                date_str = Path(current_file).with_suffix("").stem
                                results.append(
                                    {
                                        "file_path": current_file,
                                        "date": date_str,
                                        "content": "\n".join(current_lines),
                                    }
                                )
                            current_file = str(gz_file)
                            current_lines = []

                        current_lines.append(matched_line.strip())

                # 保存最后一个文件
                if current_file is not None and current_lines:
                    results.append(
                        {
                            "file_path": current_file,
                            "date": Path(current_file).with_suffix("").stem,
                            "content": "\n".join(current_lines),
                        }
                    )

        except FileNotFoundError:
            # zgrep 不可用，降级到 Python 搜索
            return self._search_python_fallback(pattern, year)

        return results

    def _search_python_fallback(
        self,
        pattern: str,
        year: Optional[Year] = None,
    ) -> List[SearchResult]:
        """Python 实现的降级搜索"""
        import re

        compiled: Pattern[str] = re.compile(pattern, re.IGNORECASE)
        results: List[SearchResult] = []

        if not self.archive_dir.exists():
            return results

        if year is not None:
            archive_files = list(
                f for f in self.archive_dir.rglob(f"*.md{self.COMPRESS_SUFFIX}")
                if f.parent.name == str(year)
            )
        else:
            archive_files = list(
                self.archive_dir.rglob(f"*.md{self.COMPRESS_SUFFIX}")
            )

        for gz_file in archive_files:
            try:
                content = self.read_compressed(gz_file)
                if compiled.search(content):
                    results.append(
                        {
                            "file_path": str(gz_file),
                            "date": gz_file.with_suffix("").stem,
                            "content": content,
                        }
                    )
            except Exception:
                continue

        return results

    # ---- 读取 ----

    def read_compressed(self, file_path: Path) -> str:
        """读取压缩文件内容"""
        with gzip.open(file_path, "rt", encoding="utf-8") as f:
            return f.read()

    def read_date(self, date_str: str) -> Optional[str]:
        """
        读取指定日期的日志（自动检测是否在 archive）

        Args:
            date_str: YYYY-MM-DD 格式

        Returns:
            日志内容，不存在返回 None
        """
        # date_str 可能是 "2026-03-15" 或 "2026-3-5" 格式
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            # 尝试柔性解析
            date_str = self._normalize_date(date_str)
            if date_str is None:
                return None

        # 先检查普通目录
        normal_path: Path = self.memory_dir / f"{date_str}.md"
        if normal_path.exists():
            return normal_path.read_text(encoding="utf-8")

        # 再检查 archive
        archive_path: Path = (
            self.archive_dir / date_str[:4] / f"{date_str}.md{self.COMPRESS_SUFFIX}"
        )
        if archive_path.exists():
            return self.read_compressed(archive_path)

        return None

    def _normalize_date(self, date_str: str) -> Optional[str]:
        """将短格式日期转为标准格式，失败返回 None"""
        try:
            parts: List[str] = date_str.split("-")
            if len(parts) != 3:
                return None
            return f"{int(parts[0])}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        except (ValueError, IndexError):
            return None

    # ---- 统计 ----

    def get_stats(self) -> StatsResult:
        """获取归档统计"""
        total_original: int = 0
        total_compressed: int = 0
        file_count_normal: int = 0
        file_count_archive: int = 0

        # 普通日志
        for f in self.memory_dir.glob("????-??-??.md"):
            total_original += f.stat().st_size
            file_count_normal += 1

        # 归档
        for f in self.archive_dir.rglob(f"*.md{self.COMPRESS_SUFFIX}"):
            total_compressed += f.stat().st_size
            file_count_archive += 1

        return {
            "normal_logs": {"count": file_count_normal, "size_bytes": total_original},
            "archived_logs": {
                "count": file_count_archive,
                "size_bytes": total_compressed,
            },
            "total_size_bytes": total_original + total_compressed,
            "compression_saved": max(0, total_original - total_compressed),
            "archive_dir": str(self.archive_dir),
        }


# ---- 入口 ----

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Memory Archive CLI")
    parser.add_argument(
        "action",
        choices=["archive", "search", "stats", "read"],
    )
    parser.add_argument("--days", type=int, default=30, help="天数阈值")
    parser.add_argument("--query", help="搜索关键词")
    parser.add_argument("--year", type=int, help="指定年份")
    parser.add_argument("--date", help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="演练模式")

    args = parser.parse_args()
    archiver = MemoryArchiver()

    if args.action == "archive":
        result = archiver.archive_old_logs(days=args.days, dry_run=args.dry_run)
        print(result)

    elif args.action == "search":
        results = archiver.search(
            query=args.query, year=args.year, days=args.days
        )
        for r in results:
            print(f"\n### {r['date']} ###")
            print(r["content"][:500])

    elif args.action == "stats":
        print(archiver.get_stats())

    elif args.action == "read":
        content = archiver.read_date(args.date)
        print(content if content else "Not found")
