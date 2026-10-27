"""Vitest JSON reporter parsing.

Vitest's JSON reporter is close to Jest's: a ``testResults`` array with a ``name`` and
``assertionResults``. We match result file names back to generated proposal paths so a
single failing file does not make every proposal look verified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_RESULTS_BYTES = 5_000_000


@dataclass(frozen=True)
class FileTestResult:
    passed: bool
    failure: str = ""
    total: int = 0


def parse_vitest_results_file(path: Path, known_paths: set[str]) -> dict[str, FileTestResult]:
    if not path.is_file():
        return {}
    try:
        if path.stat().st_size > MAX_RESULTS_BYTES:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parse_vitest_results(data, known_paths)


def parse_vitest_results(data: object, known_paths: set[str]) -> dict[str, FileTestResult]:
    if not isinstance(data, dict):
        return {}
    raw_results = data.get("testResults")
    if not isinstance(raw_results, list):
        return {}
    normalized_known = {PurePosixPath(item.replace("\\", "/")) for item in known_paths}
    results: dict[str, FileTestResult] = {}
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", "")).replace("\\", "/")
        matched = _match_path(name, normalized_known)
        if matched is None:
            continue
        assertions = raw.get("assertionResults")
        if not isinstance(assertions, list) or not assertions:
            results[matched] = FileTestResult(False, "test file produced no assertions", 0)
            continue
        failures: list[str] = []
        total = 0
        for assertion in assertions:
            if not isinstance(assertion, dict):
                continue
            total += 1
            status = str(assertion.get("status", ""))
            if status in {"pending", "skipped", "todo", "disabled"}:
                failures.append(f"skipped assertion: {assertion.get('title', '')}")
            elif status != "passed":
                failures.append(
                    str(assertion.get("failureMessages") or assertion.get("title") or status)
                )
        message = raw.get("message")
        if isinstance(message, str) and message.strip() and total == 0:
            failures.append(message)
        raw_status = str(raw.get("status", "passed"))
        passed = total > 0 and not failures and raw_status in {"passed", "pass", ""}
        results[matched] = FileTestResult(
            passed=passed,
            failure="\n".join(failures)[:4000] if failures else "",
            total=total,
        )
    return results


def _match_path(name: str, known: set[PurePosixPath]) -> str | None:
    candidate = PurePosixPath(name.lstrip("/"))
    for path in known:
        if candidate == path or candidate.as_posix().endswith("/" + path.as_posix()):
            return path.as_posix()
    return None
