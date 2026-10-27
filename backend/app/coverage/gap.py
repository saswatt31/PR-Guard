"""Coverage gap detection.

Signal order:
1. Istanbul function hit count (authoritative when a baseline coverage run exists).
2. A test file that mentions the function name (fallback heuristic).
3. A sibling test file for ``default`` exports / as a hint.

The fallback intentionally errs toward reporting a gap when uncertain: proposing a
test for already-tested code is cheaper than missing untested code.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from app.coverage.istanbul import CoverageReport
from app.diff.models import FunctionInfo

TEST_FILE_SUFFIXES = (
    ".test.ts",
    ".test.tsx",
    ".test.js",
    ".test.jsx",
    ".spec.ts",
    ".spec.tsx",
    ".spec.js",
    ".spec.jsx",
)
TEST_DIR_NAMES = {"__tests__", "test", "tests", "e2e"}
SKIP_DIRS = {
    "node_modules",
    ".git",
    ".next",
    "dist",
    "build",
    "coverage",
    "playwright-report",
    "test-results",
    "vendor",
}
MAX_TEST_FILES = 2000
MAX_TEST_FILE_BYTES = 500_000
MAX_TOTAL_TEST_BYTES = 20_000_000


@dataclass(frozen=True)
class GapDecision:
    function: FunctionInfo
    reason: str
    existing_tests: tuple[str, ...] = ()


@dataclass
class GapResult:
    gaps: list[GapDecision] = field(default_factory=list)
    covered: list[GapDecision] = field(default_factory=list)
    skipped: list[GapDecision] = field(default_factory=list)


def is_test_file(path: str) -> bool:
    pure = PurePosixPath(path)
    if pure.name.endswith(TEST_FILE_SUFFIXES):
        return True
    return bool(set(pure.parts[:-1]) & TEST_DIR_NAMES) and pure.suffix in {
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
    }


def find_gaps(
    functions: list[FunctionInfo],
    repo_root: Path,
    *,
    coverage: CoverageReport | None = None,
    enabled_paths: list[str] | None = None,
) -> GapResult:
    root = repo_root.resolve()
    test_files = _scan_test_files(root)
    contents = _read_test_files(test_files)
    result = GapResult()

    for function in functions:
        path = function.file_path.replace("\\", "/")
        if is_test_file(path):
            result.skipped.append(GapDecision(function, "file is a test file"))
            continue
        if not _enabled(path, enabled_paths):
            result.skipped.append(GapDecision(function, "path disabled by .prguard.yml"))
            continue
        if not function.exported:
            result.skipped.append(
                GapDecision(function, "not exported; a unit test cannot import it")
            )
            continue
        if not function.name or function.name == "default":
            # Default exports can be imported under any local name; fall back to sibling
            # test detection rather than name matching.
            sibling = _sibling_tests(root, function.file_path)
            if sibling:
                result.covered.append(
                    GapDecision(function, "sibling test file exists", tuple(sibling))
                )
            else:
                result.gaps.append(
                    GapDecision(function, "no sibling test file for default export")
                )
            continue

        coverage_hits = None
        if coverage is not None:
            coverage_hits = coverage.function_hits(
                function.file_path, function.name, function.start_line, function.end_line
            )
        references = _find_references(function.name, contents, root)
        sibling = _sibling_tests(root, function.file_path)

        if coverage_hits is not None and coverage_hits > 0:
            result.covered.append(
                GapDecision(
                    function,
                    f"coverage shows {coverage_hits} execution(s)",
                    tuple(sorted(set(references))),
                )
            )
        elif coverage_hits == 0:
            result.gaps.append(
                GapDecision(
                    function,
                    "coverage shows 0 executions",
                    tuple(sorted(set(references) | set(sibling))),
                )
            )
        elif references:
            result.covered.append(
                GapDecision(function, "existing test references the function", tuple(references))
            )
        else:
            result.gaps.append(
                GapDecision(
                    function,
                    "no existing test references the function",
                    tuple(sibling),
                )
            )

    return result


def _enabled(path: str, patterns: list[str] | None) -> bool:
    if not patterns:
        return True
    for raw in patterns:
        pattern = raw.strip().replace("\\", "/")
        if not pattern:
            continue
        if pattern.endswith("/**"):
            base = pattern[:-3].rstrip("/")
            if path == base or path.startswith(base + "/"):
                return True
        elif fnmatchcase(path, pattern):
            return True
    return False


def _scan_test_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        for filename in filenames:
            relative = (Path(dirpath) / filename).relative_to(root).as_posix()
            if is_test_file(relative):
                found.append(Path(dirpath) / filename)
                if len(found) >= MAX_TEST_FILES:
                    return found
    return found


def _read_test_files(paths: list[Path]) -> dict[Path, str]:
    contents: dict[Path, str] = {}
    total = 0
    for path in paths:
        try:
            if path.stat().st_size > MAX_TEST_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        total += len(text)
        if total > MAX_TOTAL_TEST_BYTES:
            break
        contents[path] = text
    return contents


def _find_references(name: str, contents: dict[Path, str], root: Path) -> list[str]:
    if not name:
        return []
    # Word/identifier boundary that also handles `$` in JS identifiers.
    pattern = re.compile(rf"(?<![\w$]){re.escape(name)}(?![\w$])")
    found: list[str] = []
    for path, text in contents.items():
        if pattern.search(text):
            try:
                found.append(path.relative_to(root).as_posix())
            except ValueError:  # pragma: no cover - scanned paths are under root
                found.append(path.as_posix())
    return found


def _sibling_tests(root: Path, file_path: str) -> list[str]:
    source = root / PurePosixPath(file_path)
    stem = source.stem
    candidates = [
        source.with_name(stem + suffix) for suffix in TEST_FILE_SUFFIXES
    ]
    candidates.extend(
        source.parent / "__tests__" / (stem + suffix) for suffix in TEST_FILE_SUFFIXES
    )
    found: list[str] = []
    for candidate in candidates:
        if candidate.is_file():
            try:
                found.append(candidate.relative_to(root).as_posix())
            except ValueError:  # pragma: no cover - candidate is built under root
                continue
    return sorted(set(found))
