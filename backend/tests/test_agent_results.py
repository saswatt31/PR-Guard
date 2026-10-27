"""Tests for Vitest JSON result parsing and per-file attribution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents import results as results_module
from app.agents.results import parse_vitest_results, parse_vitest_results_file


def assertion(status: str = "passed", title: str = "adds") -> dict[str, object]:
    return {"title": title, "status": status}


def parsed(
    *,
    name: str = "src/math.add.test.ts",
    assertions: list[object] | None = None,
    status: str = "passed",
    message: str | None = None,
) -> dict[str, object]:
    raw: dict[str, object] = {
        "name": name,
        "status": status,
        "assertionResults": [assertion()] if assertions is None else assertions,
    }
    if message is not None:
        raw["message"] = message
    return {"testResults": [raw]}


def test_parse_passed_file() -> None:
    result = parse_vitest_results(parsed(), {"src/math.add.test.ts"})

    assert result["src/math.add.test.ts"].passed is True
    assert result["src/math.add.test.ts"].failure == ""
    assert result["src/math.add.test.ts"].total == 1


@pytest.mark.parametrize(
    "name",
    [
        "/home/runner/work/repo/src/math.add.test.ts",
        "C:\\repo\\src\\math.add.test.ts",
        "./src/math.add.test.ts",
    ],
)
def test_parse_matches_absolute_windows_and_dotted_names(name: str) -> None:
    result = parse_vitest_results(parsed(name=name), {"src/math.add.test.ts"})

    assert result["src/math.add.test.ts"].passed is True


def test_parse_ignores_unknown_files_and_invalid_shapes() -> None:
    assert parse_vitest_results(parsed(name="src/other.test.ts"), {"src/math.test.ts"}) == {}
    assert parse_vitest_results([], {"src/math.test.ts"}) == {}
    assert parse_vitest_results({}, {"src/math.test.ts"}) == {}
    assert parse_vitest_results({"testResults": "nope"}, {"src/math.test.ts"}) == {}
    assert parse_vitest_results({"testResults": [None, 3]}, {"src/math.test.ts"}) == {}


def test_file_without_assertions_fails() -> None:
    result = parse_vitest_results(parsed(assertions=[]), {"src/math.add.test.ts"})

    assert result["src/math.add.test.ts"].passed is False
    assert "no assertions" in result["src/math.add.test.ts"].failure
    assert result["src/math.add.test.ts"].total == 0


@pytest.mark.parametrize("status", ["pending", "skipped", "todo", "disabled"])
def test_skipped_assertions_fail_the_file(status: str) -> None:
    result = parse_vitest_results(
        parsed(assertions=[assertion("passed"), assertion(status, "later")]),
        {"src/math.add.test.ts"},
    )

    assert result["src/math.add.test.ts"].passed is False
    assert "skipped assertion: later" in result["src/math.add.test.ts"].failure


def test_failed_assertion_uses_failure_messages() -> None:
    failed = {
        "status": "failed",
        "title": "adds",
        "failureMessages": "AssertionError: expected 3 to be 4",
    }
    result = parse_vitest_results(parsed(assertions=[failed]), {"src/math.add.test.ts"})

    assert result["src/math.add.test.ts"].passed is False
    assert "expected 3 to be 4" in result["src/math.add.test.ts"].failure
    assert result["src/math.add.test.ts"].total == 1


def test_failed_assertion_falls_back_to_title() -> None:
    failed = {"status": "failed", "title": "adds", "failureMessages": ""}
    result = parse_vitest_results(parsed(assertions=[failed]), {"src/math.add.test.ts"})

    assert result["src/math.add.test.ts"].failure == "adds"


def test_non_dict_assertion_is_ignored_but_message_is_reported() -> None:
    result = parse_vitest_results(
        parsed(assertions=["not a dict"], message="suite crashed"),
        {"src/math.add.test.ts"},
    )

    assert result["src/math.add.test.ts"].passed is False
    assert result["src/math.add.test.ts"].total == 0
    assert "suite crashed" in result["src/math.add.test.ts"].failure


def test_raw_failed_status_fails_even_with_passing_assertions() -> None:
    result = parse_vitest_results(parsed(status="failed"), {"src/math.add.test.ts"})

    assert result["src/math.add.test.ts"].passed is False
    assert result["src/math.add.test.ts"].total == 1


def test_failure_text_is_truncated_to_4000_characters() -> None:
    failed = {"status": "failed", "title": "x" * 5000, "failureMessages": ""}
    result = parse_vitest_results(parsed(assertions=[failed]), {"src/math.add.test.ts"})

    assert len(result["src/math.add.test.ts"].failure) == 4000


def test_parse_results_file_missing_invalid_and_oversized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.json"
    assert parse_vitest_results_file(missing, {"src/math.test.ts"}) == {}

    invalid = tmp_path / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")
    assert parse_vitest_results_file(invalid, {"src/math.test.ts"}) == {}

    large = tmp_path / "large.json"
    large.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(results_module, "MAX_RESULTS_BYTES", 1)

    def refuse_read(self: Path, *args: object, **kwargs: object) -> str:
        raise AssertionError("oversized file should not be read")

    monkeypatch.setattr(Path, "read_text", refuse_read)
    assert parse_vitest_results_file(large, {"src/math.test.ts"}) == {}


def test_parse_results_file_reads_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text(json.dumps(parsed()), encoding="utf-8")

    result = parse_vitest_results_file(path, {"src/math.add.test.ts"})

    assert result["src/math.add.test.ts"].passed is True
