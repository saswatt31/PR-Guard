"""Istanbul/V8 coverage JSON parsing.

Vitest's ``json`` reporter (or ``coverage-final.json``) records per-function hit
counts. That is the strongest signal for "does this function already have an
executing test?" and it is used by the gap finder when a baseline run is available.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True)
class FunctionCoverage:
    name: str
    start_line: int
    end_line: int
    hits: int


@dataclass
class FileCoverage:
    path: str
    functions: list[FunctionCoverage] = field(default_factory=list)


@dataclass
class CoverageReport:
    files: dict[str, FileCoverage] = field(default_factory=dict)
    line_pct: float | None = None

    def for_file(self, repo_relative_path: str) -> FileCoverage | None:
        normalized = repo_relative_path.replace("\\", "/").lstrip("./")
        if normalized in self.files:
            return self.files[normalized]
        suffix = "/" + normalized
        for path, coverage in self.files.items():
            if path.replace("\\", "/").endswith(suffix):
                return coverage
        # Last resort for container paths whose prefix was stripped differently.
        name = PurePosixPath(normalized).name
        matches = [
            coverage
            for path, coverage in self.files.items()
            if PurePosixPath(path.replace("\\", "/")).name == name
        ]
        return matches[0] if len(matches) == 1 else None

    def function_hits(
        self, repo_relative_path: str, name: str, start_line: int, end_line: int
    ) -> int | None:
        """Return hit count, or None when the function isn't present in the report."""

        file_coverage = self.for_file(repo_relative_path)
        if file_coverage is None:
            return None
        candidates = [fn for fn in file_coverage.functions if fn.name == name]
        if not candidates:
            return None
        overlapping = [
            fn
            for fn in candidates
            if fn.start_line <= end_line and fn.end_line >= start_line
        ]
        if overlapping:
            return max(fn.hits for fn in overlapping)
        # Duplicate names (e.g. two classes) are disambiguated by proximity.
        nearest = min(candidates, key=lambda fn: abs(fn.start_line - start_line))
        if abs(nearest.start_line - start_line) <= 5:
            return nearest.hits
        return None


def parse_istanbul_coverage(data: dict[str, Any], repo_root: Path | None = None) -> CoverageReport:
    report = CoverageReport()
    total = data.get("total")
    if isinstance(total, dict):
        lines = total.get("lines")
        if isinstance(lines, dict) and isinstance(lines.get("pct"), (int, float)):
            report.line_pct = float(lines["pct"])

    for raw_path, entry in data.items():
        if raw_path == "total" or not isinstance(entry, dict):
            continue
        if "fnMap" not in entry:
            continue
        path = _relative_path(raw_path, repo_root)
        functions: list[FunctionCoverage] = []
        fn_map = entry.get("fnMap", {})
        hits = entry.get("f", {})
        if not isinstance(fn_map, dict):
            continue
        for key, descriptor in fn_map.items():
            if not isinstance(descriptor, dict):
                continue
            decl = descriptor.get("decl", {})
            loc = descriptor.get("loc", {})
            start = (decl.get("start") or loc.get("start") or {}).get("line", 0)
            end = (decl.get("end") or loc.get("end") or {}).get("line", start)
            functions.append(
                FunctionCoverage(
                    name=str(descriptor.get("name", "")),
                    start_line=int(start or 0),
                    end_line=int(end or start or 0),
                    hits=int(hits.get(str(key), hits.get(key, 0)) or 0)
                    if isinstance(hits, dict)
                    else 0,
                )
            )
        report.files[path] = FileCoverage(path=path, functions=functions)

    if report.line_pct is None:
        report.line_pct = _compute_line_pct(data)
    return report


def load_coverage_file(path: Path, repo_root: Path | None = None) -> CoverageReport:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("coverage JSON must be an object")
    return parse_istanbul_coverage(data, repo_root=repo_root)


def _relative_path(raw_path: str, repo_root: Path | None) -> str:
    normalized = raw_path.replace("\\", "/")
    if repo_root is not None:
        root = str(repo_root.resolve()).replace("\\", "/").rstrip("/")
        if normalized.startswith(root + "/"):
            return normalized[len(root) + 1 :]
    # Container paths are often /workspace/repo/<relative>.
    for marker in ("/workspace/repo/", "/repo/", "/workspace/"):
        if marker in normalized:
            return normalized.split(marker, 1)[1]
    return normalized.lstrip("/")


def _compute_line_pct(data: dict[str, Any]) -> float | None:
    hit = 0
    total = 0
    for path, entry in data.items():
        if path == "total" or not isinstance(entry, dict):
            continue
        statements = entry.get("statementMap", {})
        counts = entry.get("s", {})
        if not isinstance(statements, dict) or not isinstance(counts, dict):
            continue
        for key, statement in statements.items():
            if not isinstance(statement, dict):
                continue
            total += 1
            if int(counts.get(str(key), counts.get(key, 0)) or 0) > 0:
                hit += 1
    if total == 0:
        return None
    return round(hit / total * 100, 2)
