"""GZipMemory unit tests."""

from __future__ import annotations

import gzip
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    from archiver import MemoryArchiver
except ImportError:
    from GZipMemory.archiver import MemoryArchiver


def test_compress_and_decompress(tmp_path: Path) -> None:
    """Test compress/decompress of _compress_file."""
    archiver = MemoryArchiver(base_dir=str(tmp_path))

    test_file = tmp_path / "memory" / "2026-01-01.md"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_content = "test content: Hello World"
    test_file.write_text(test_content, encoding="utf-8")

    compressed = archiver._compress_file(test_file)  # noqa: SLF001
    assert isinstance(compressed, bytes)

    decompressed = gzip.decompress(compressed).decode("utf-8")
    assert decompressed == test_content


def test_safe_archive_flow(tmp_path: Path) -> None:
    """Test safe archiving flow (compress + move + verify + delete original)."""
    archiver = MemoryArchiver(base_dir=str(tmp_path))

    test_file = tmp_path / "memory" / "2026-01-01.md"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_content = "test content: Hello World"
    test_file.write_text(test_content, encoding="utf-8")

    result = archiver._safe_archive(test_file)  # noqa: SLF001
    assert result is True
    assert not test_file.exists()

    gz_path = tmp_path / "memory" / "archive" / "2026" / "2026-01-01.md.gz"
    assert gz_path.exists()

    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
        dec = f.read()
    assert dec == test_content


def test_read_date_normal(tmp_path: Path) -> None:
    """Test reading normal log (not archived)."""
    archiver = MemoryArchiver(base_dir=str(tmp_path))

    date_str = "2026-03-15"
    log_file = tmp_path / "memory" / f"{date_str}.md"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("# 2026-03-15 log content", encoding="utf-8")

    content = archiver.read_date(date_str)
    assert content is not None
    assert "2026-03-15" in content


def test_read_date_archived(tmp_path: Path) -> None:
    """Test reading archived log (when normal log does not exist)."""
    archiver = MemoryArchiver(base_dir=str(tmp_path))

    archive_dir = tmp_path / "memory" / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)

    date_str = "2026-02-20"
    gz_file = archive_dir / f"{date_str}.md.gz"
    gz_file.write_bytes(gzip.compress(b"# 2026-02-20 archived content\n- meeting"))

    content = archiver.read_date(date_str)
    assert content is not None
    assert "archived content" in content


def test_read_date_not_found(tmp_path: Path) -> None:
    """Test reading non-existent date."""
    archiver = MemoryArchiver(base_dir=str(tmp_path))
    content = archiver.read_date("2099-12-31")
    assert content is None


def test_search_archive_by_year(tmp_path: Path) -> None:
    """Test searching by year."""
    archiver = MemoryArchiver(base_dir=str(tmp_path))

    archive_dir = tmp_path / "memory" / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)

    gz_file = archive_dir / "2026-04-01.md.gz"
    gz_file.write_bytes(gzip.compress(b"keyword: test"))

    results = archiver.search("test", year=2026)
    assert len(results) == 1
    assert results[0]["date"] == "2026-04-01"


def test_search_archive_no_results(tmp_path: Path) -> None:
    """Test searching with no results."""
    archiver = MemoryArchiver(base_dir=str(tmp_path))
    results = archiver.search("nonexistent_xyz", year=2026)
    assert len(results) == 0


if __name__ == "__main__":
    tmp = Path(tempfile.mkdtemp())

    test_compress_and_decompress(tmp)
    test_safe_archive_flow(tmp)
    test_read_date_normal(tmp)
    test_read_date_archived(tmp)
    test_read_date_not_found(tmp)
    test_search_archive_by_year(tmp)
    test_search_archive_no_results(tmp)

