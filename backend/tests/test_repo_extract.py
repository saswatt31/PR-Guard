import io
import tarfile
from pathlib import Path

import pytest

from app.github.errors import RepoExtractionError
from app.github.repo import safe_extract_tarball


def tar_bytes(entries: list[tuple[str, bytes | None, bytes | None]]) -> bytes:
    """entries = (name, file bytes or None for dir, type flag or None)."""

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data, member_type in entries:
            info = tarfile.TarInfo(name)
            if member_type is not None:
                info.type = member_type
                info.linkname = "target"
                archive.addfile(info)
            elif data is None:
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            else:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_extracts_repository_and_strips_root(tmp_path: Path) -> None:
    data = tar_bytes(
        [
            ("acme-demo-sha", None, None),
            ("acme-demo-sha/package.json", b'{"name":"demo"}', None),
            ("acme-demo-sha/src/math.ts", b"export const add = (a: number) => a + 1", None),
        ]
    )
    written = safe_extract_tarball(data, tmp_path / "repo")
    assert written == 2
    assert (tmp_path / "repo" / "package.json").read_text() == '{"name":"demo"}'
    assert (tmp_path / "repo" / "src" / "math.ts").exists()


@pytest.mark.parametrize(
    "name",
    [
        "/etc/passwd",
        "root/../../evil.txt",
        "root/../evil.txt",
        "root\\..\\evil.txt",
    ],
)
def test_rejects_absolute_and_traversal_paths(tmp_path: Path, name: str) -> None:
    data = tar_bytes([(name, b"evil", None)])
    with pytest.raises(RepoExtractionError):
        safe_extract_tarball(data, tmp_path / "repo")
    assert not (tmp_path / "evil.txt").exists()


def test_rejects_symlinks(tmp_path: Path) -> None:
    data = tar_bytes([("root/link", None, tarfile.SYMTYPE)])
    with pytest.raises(RepoExtractionError, match="unsupported"):
        safe_extract_tarball(data, tmp_path / "repo")


def test_rejects_hardlinks(tmp_path: Path) -> None:
    data = tar_bytes([("root/link", None, tarfile.LNKTYPE)])
    with pytest.raises(RepoExtractionError, match="unsupported"):
        safe_extract_tarball(data, tmp_path / "repo")


def test_rejects_duplicate_members(tmp_path: Path) -> None:
    data = tar_bytes(
        [
            ("root/a.txt", b"one", None),
            ("root/a.txt", b"two", None),
        ]
    )
    with pytest.raises(RepoExtractionError, match="duplicate"):
        safe_extract_tarball(data, tmp_path / "repo")


def test_rejects_too_many_entries(tmp_path: Path) -> None:
    data = tar_bytes([(f"root/{i}.txt", b"x", None) for i in range(3)])
    with pytest.raises(RepoExtractionError, match="more than 2"):
        safe_extract_tarball(data, tmp_path / "repo", max_files=2)


def test_rejects_uncompressed_size_limit(tmp_path: Path) -> None:
    data = tar_bytes([("root/big.txt", b"x" * 20, None)])
    with pytest.raises(RepoExtractionError, match="expands beyond"):
        safe_extract_tarball(data, tmp_path / "repo", max_bytes=10)


def test_rejects_invalid_archive(tmp_path: Path) -> None:
    with pytest.raises(RepoExtractionError, match="invalid repository archive"):
        safe_extract_tarball(b"not a tar", tmp_path / "repo")


def test_ignores_root_directory_entry(tmp_path: Path) -> None:
    data = tar_bytes([("root", None, None), ("root/file.ts", b"x", None)])
    assert safe_extract_tarball(data, tmp_path / "repo") == 1
