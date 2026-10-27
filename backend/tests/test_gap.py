from dataclasses import replace
from pathlib import Path

from app.coverage.gap import find_gaps, is_test_file
from app.coverage.istanbul import parse_istanbul_coverage
from app.diff.extract import extract_functions
from app.diff.models import FunctionInfo

MATH = """\
export function add(a: number, b: number) { return a + b; }
export function sub(a: number, b: number) { return a - b; }
export function multiply(a: number, b: number) { return a * b; }
function internal(a: number) { return a; }
"""

MATH_TEST = """\
import { add } from "./math";
describe("add", () => {
  it("adds", () => expect(add(1, 2)).toBe(3));
});
"""

WIDGET = """\
export default function () {
  return null;
}
"""


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def make_repo(tmp_path: Path) -> tuple[list[FunctionInfo], Path]:
    write(tmp_path, "src/math.ts", MATH)
    write(tmp_path, "src/math.test.ts", MATH_TEST)
    write(tmp_path, "src/widget.tsx", WIDGET)
    write(tmp_path, "src/__tests__/widget.test.tsx", "it('renders', () => {});\n")
    write(tmp_path, "node_modules/pkg/ignored.test.ts", "add sub multiply\n")
    functions = extract_functions(MATH, "src/math.ts") + extract_functions(WIDGET, "src/widget.tsx")
    return functions, tmp_path


def coverage_report():
    return parse_istanbul_coverage(
        {
            "src/math.ts": {
                "fnMap": {
                    "0": {"name": "add", "decl": {"start": {"line": 1}, "end": {"line": 1}}},
                    "1": {"name": "sub", "decl": {"start": {"line": 2}, "end": {"line": 2}}},
                },
                "f": {"0": 0, "1": 3},
            }
        }
    )


def test_detects_gaps_and_skips_unexported(tmp_path: Path) -> None:
    functions, root = make_repo(tmp_path)
    result = find_gaps(functions, root)
    gaps = {decision.function.name for decision in result.gaps}
    # add is referenced by a test, sub and multiply are not.
    assert gaps == {"sub", "multiply"}
    skipped = {decision.function.name: decision.reason for decision in result.skipped}
    assert "internal" in skipped
    assert "not exported" in skipped["internal"]
    covered = {decision.function.name for decision in result.covered}
    assert "add" in covered


def test_coverage_zero_overrides_test_reference(tmp_path: Path) -> None:
    functions, root = make_repo(tmp_path)
    result = find_gaps(functions, root, coverage=coverage_report())
    gap_names = {decision.function.name for decision in result.gaps}
    assert "add" in gap_names
    assert "sub" not in gap_names
    assert any("coverage shows 0" in decision.reason for decision in result.gaps)
    assert any(decision.function.name == "sub" for decision in result.covered)


def test_coverage_hits_cover_even_without_reference(tmp_path: Path) -> None:
    functions, root = make_repo(tmp_path)
    result = find_gaps(functions, root, coverage=coverage_report())
    sub = next(d for d in result.covered if d.function.name == "sub")
    assert "3 execution" in sub.reason


def test_default_export_uses_sibling_test(tmp_path: Path) -> None:
    functions, root = make_repo(tmp_path)
    result = find_gaps(functions, root)
    widget = next(d for d in result.covered if d.function.name == "default")
    assert "sibling" in widget.reason
    assert "src/__tests__/widget.test.tsx" in widget.existing_tests


def test_default_export_without_sibling_is_gap(tmp_path: Path) -> None:
    write(tmp_path, "src/lone.tsx", WIDGET)
    functions = extract_functions(WIDGET, "src/lone.tsx")
    result = find_gaps(functions, tmp_path)
    assert [d.function.name for d in result.gaps] == ["default"]


def test_enabled_paths_filter(tmp_path: Path) -> None:
    functions, root = make_repo(tmp_path)
    result = find_gaps(functions, root, enabled_paths=["lib/**"])
    assert result.gaps == []
    assert result.covered == []
    assert all(d.reason == "path disabled by .prguard.yml" for d in result.skipped)


def test_enabled_paths_supports_glob_and_directory_patterns(tmp_path: Path) -> None:
    functions, root = make_repo(tmp_path)
    result = find_gaps(functions, root, enabled_paths=["src/**", "lib/**"])
    assert {d.function.name for d in result.gaps} == {"sub", "multiply"}
    result = find_gaps(functions, root, enabled_paths=["src/*.ts"])
    assert {d.function.name for d in result.gaps} == {"sub", "multiply"}
    assert all(d.function.file_path == "src/math.ts" for d in result.gaps)
    assert any(d.function.name == "default" and "path disabled" in d.reason for d in result.skipped)


def test_test_file_function_is_skipped(tmp_path: Path) -> None:
    functions, root = make_repo(tmp_path)
    [function] = functions[:1]
    test_function = replace(function, file_path="src/math.test.ts")
    result = find_gaps([test_function], root)
    assert result.skipped[0].reason == "file is a test file"


def test_test_file_detection() -> None:
    assert is_test_file("src/a.test.ts") is True
    assert is_test_file("src/a.spec.tsx") is True
    assert is_test_file("tests/helper.ts") is True
    assert is_test_file("src/a.ts") is False
    assert is_test_file("src/contest/test.tsx") is False


def test_node_modules_tests_are_not_scanned(tmp_path: Path) -> None:
    write(tmp_path, "src/a.ts", "export function lonely() { return 1; }\n")
    write(tmp_path, "node_modules/pkg/x.test.ts", "lonely();\n")
    functions = extract_functions("export function lonely() { return 1; }\n", "src/a.ts")
    result = find_gaps(functions, tmp_path)
    assert [d.function.name for d in result.gaps] == ["lonely"]
