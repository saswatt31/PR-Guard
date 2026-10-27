"""Orchestrates diff parsing and function extraction against a checked-out tree."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from app.diff.extract import extract_functions, mark_only_changed
from app.diff.models import DiffAnalysis
from app.diff.parser import parse_diff

MAX_SOURCE_BYTES = 1_500_000


def analyze_diff(diff_text: str, repo_root: Path) -> DiffAnalysis:
    root = repo_root.resolve()
    analysis = DiffAnalysis(files=parse_diff(diff_text))

    for file_diff in analysis.files:
        if file_diff.status == "deleted" or file_diff.is_binary:
            continue
        pure = PurePosixPath(file_diff.path)
        if pure.is_absolute() or ".." in pure.parts:
            analysis.errors.append(f"unsafe diff path skipped: {file_diff.path}")
            continue
        path = (root / pure).resolve()
        if path != root and root not in path.parents:
            analysis.errors.append(f"diff path escapes repository: {file_diff.path}")
            continue
        if not path.is_file():
            analysis.errors.append(f"changed file not found in checkout: {file_diff.path}")
            continue
        if path.stat().st_size > MAX_SOURCE_BYTES:
            analysis.errors.append(f"changed file too large to analyse: {file_diff.path}")
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            analysis.errors.append(f"could not read {file_diff.path}: {exc}")
            continue

        functions = extract_functions(source, file_diff.path)
        analysis.functions.extend(
            mark_only_changed(
                functions,
                file_diff.changed_new_lines,
                is_new_file=file_diff.status == "added",
                added_lines=file_diff.added_lines,
            )
        )

    return analysis
