import json
from pathlib import Path

from app.coverage.istanbul import (
    CoverageReport,
    load_coverage_file,
    parse_istanbul_coverage,
)

SAMPLE = {
    "total": {"lines": {"pct": 66.67}},
    "/tmp/repo/src/math.ts": {
        "fnMap": {
            "0": {
                "name": "add",
                "decl": {"start": {"line": 1}, "end": {"line": 3}},
                "loc": {"start": {"line": 1}, "end": {"line": 3}},
            },
            "1": {
                "name": "sub",
                "decl": {"start": {"line": 10}, "end": {"line": 12}},
                "loc": {"start": {"line": 10}, "end": {"line": 12}},
            },
        },
        "f": {"0": 0, "1": 4},
        "statementMap": {
            "0": {"start": {"line": 1}},
            "1": {"start": {"line": 2}},
        },
        "s": {"0": 1, "1": 0},
    },
}


def test_parses_function_hits_and_total() -> None:
    report = parse_istanbul_coverage(SAMPLE, repo_root=Path("/tmp/repo"))
    assert report.line_pct == 66.67
    assert report.function_hits("src/math.ts", "add", 1, 3) == 0
    assert report.function_hits("src/math.ts", "sub", 10, 12) == 4
    assert report.function_hits("src/math.ts", "missing", 1, 3) is None


def test_matches_absolute_paths_and_suffixes() -> None:
    report = parse_istanbul_coverage(SAMPLE)
    assert report.for_file("src/math.ts") is not None
    assert report.function_hits("/tmp/repo/src/math.ts", "add", 1, 3) == 0


def test_computes_line_pct_when_total_missing() -> None:
    data = json.loads(json.dumps(SAMPLE))
    data.pop("total")
    report = parse_istanbul_coverage(data, repo_root=Path("/tmp/repo"))
    assert report.line_pct == 50.0


def test_duplicate_names_disambiguated_by_line_proximity() -> None:
    report = parse_istanbul_coverage(
        {
            "repo/src/a.ts": {
                "fnMap": {
                    "0": {"name": "run", "decl": {"start": {"line": 2}, "end": {"line": 4}}},
                    "1": {"name": "run", "decl": {"start": {"line": 40}, "end": {"line": 42}}},
                },
                "f": {"0": 7, "1": 0},
            }
        }
    )
    assert report.function_hits("src/a.ts", "run", 2, 4) == 7
    assert report.function_hits("src/a.ts", "run", 40, 42) == 0
    # No overlap and not close to either declaration.
    assert report.function_hits("src/a.ts", "run", 80, 90) is None


def test_load_coverage_file(tmp_path: Path) -> None:
    path = tmp_path / "coverage-final.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")
    report = load_coverage_file(path, repo_root=Path("/tmp/repo"))
    assert isinstance(report, CoverageReport)
    assert report.function_hits("src/math.ts", "sub", 10, 12) == 4


def test_ignores_total_entries_and_missing_fnmap() -> None:
    report = parse_istanbul_coverage(
        {"total": {"lines": {"pct": 10}}, "repo/src/a.ts": {"statementMap": {}}}
    )
    assert report.files == {}
    assert report.line_pct == 10


def test_empty_report_has_no_line_pct() -> None:
    report = parse_istanbul_coverage({})
    assert report.line_pct is None
    assert report.for_file("src/missing.ts") is None
