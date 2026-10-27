"""Safely extract a GitHub tarball into a workspace.

Repository contents are untrusted. We reject absolute paths, traversal, symlinks,
hardlinks, duplicate entries and oversized archives before any file is written.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path, PurePosixPath

from app.github.errors import RepoExtractionError

MAX_FILES = 20_000
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


def safe_extract_tarball(
    data: bytes,
    destination: Path,
    *,
    max_files: int = MAX_FILES,
    max_bytes: int = MAX_UNCOMPRESSED_BYTES,
) -> int:
    """Extract ``data`` under ``destination``; return number of files written.

    GitHub tarballs have exactly one top-level directory which is stripped. Every
    member must be a regular file or directory; special files are rejected.
    """

    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    written = 0
    total_bytes = 0
    seen: set[Path] = set()

    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            members = archive.getmembers()
            if len(members) > max_files:
                raise RepoExtractionError(f"archive contains more than {max_files} entries")

            for member in members:
                if not (member.isfile() or member.isdir()):
                    raise RepoExtractionError(f"unsupported archive member: {member.name}")

                if "\\" in member.name or "\x00" in member.name:
                    raise RepoExtractionError(f"unsafe archive member name: {member.name}")

                pure = PurePosixPath(member.name)
                if pure.is_absolute() or ".." in pure.parts:
                    raise RepoExtractionError(f"path traversal in archive: {member.name}")

                parts = pure.parts[1:]  # strip GitHub's owner-repo-sha/ root
                if not parts:
                    continue
                target = destination.joinpath(*parts)
                resolved = target.resolve()
                if resolved != destination and destination not in resolved.parents:
                    raise RepoExtractionError(f"path escapes destination: {member.name}")
                if resolved in seen:
                    raise RepoExtractionError(f"duplicate archive member: {member.name}")
                seen.add(resolved)

                if member.isdir():
                    resolved.mkdir(parents=True, exist_ok=True)
                    continue

                if member.size < 0:
                    raise RepoExtractionError(f"negative size for {member.name}")
                total_bytes += member.size
                if total_bytes > max_bytes:
                    raise RepoExtractionError(f"archive expands beyond {max_bytes} bytes")

                source = archive.extractfile(member)
                if source is None:  # pragma: no cover - guarded by isfile above
                    raise RepoExtractionError(f"cannot read archive member: {member.name}")
                resolved.parent.mkdir(parents=True, exist_ok=True)
                with resolved.open("wb") as handle:
                    copied = 0
                    while chunk := source.read(64 * 1024):
                        copied += len(chunk)
                        if copied > member.size:
                            raise RepoExtractionError(f"member grew while reading: {member.name}")
                        handle.write(chunk)
                written += 1
    except (tarfile.TarError, OSError) as exc:
        raise RepoExtractionError(f"invalid repository archive: {exc}") from exc

    return written
