from app.diff.extract import extract_functions, mark_only_changed

SOURCE = """\
export function add(a: number, b: number): number {
  return a + b;
}

export async function fetchValue(id: string): Promise<number> {
  return Number(id);
}

export const multiply = (a: number, b: number) => a * b;

function internalHelper() {
  return 1;
}

export class Calculator {
  constructor(private base: number) {}
  add(a: number): number {
    return this.base + a;
  }
  private secret(): number {
    return 42;
  }
  handler = () => this.base;
}

export const api = {
  ping: () => 1,
  pong() {
    return 2;
  },
};

export default function defaultThing() {
  return "ok";
}

const later = () => 3;
export { later };

function outer() {
  function nested() {
    return 0;
  }
  return nested;
}
"""


def test_extracts_importable_top_level_functions() -> None:
    functions = extract_functions(SOURCE, "src/math.ts")
    names = {fn.qualified_name for fn in functions}
    assert "add" in names
    assert "fetchValue" in names
    assert "multiply" in names
    assert "internalHelper" in names
    assert "Calculator.add" in names
    assert "Calculator.handler" in names
    assert "api.ping" in names
    assert "api.pong" in names
    assert "defaultThing" in names
    assert "later" in names
    assert "outer" in names


def test_skips_constructor_private_and_nested_functions() -> None:
    functions = extract_functions(SOURCE, "src/math.ts")
    names = {fn.qualified_name for fn in functions}
    assert "Calculator.constructor" not in names
    assert "Calculator.secret" not in names
    assert "nested" not in names
    assert "outer.nested" not in names


def test_export_and_metadata_flags() -> None:
    functions = {fn.qualified_name: fn for fn in extract_functions(SOURCE, "src/math.ts")}
    assert functions["add"].exported is True
    assert functions["fetchValue"].is_async is True
    assert functions["multiply"].exported is True
    assert functions["internalHelper"].exported is False
    assert functions["Calculator.add"].exported is True
    assert functions["Calculator.add"].container == "Calculator"
    assert functions["later"].exported is True
    assert "export async function fetchValue" in functions["fetchValue"].signature
    assert functions["multiply"].signature.startswith("export const multiply")


def test_line_ranges_and_source_are_available() -> None:
    functions = extract_functions(SOURCE, "src/math.ts")
    add = next(fn for fn in functions if fn.name == "add")
    assert add.start_line == 1
    assert add.end_line == 3
    assert "return a + b" in add.source


def test_tsx_and_ui_detection() -> None:
    source = """\
export function Button() {
  return <button>Click</button>;
}
export const Label = () => <span>Hi</span>;
"""
    functions = extract_functions(source, "src/components/Button.tsx")
    assert len(functions) == 2
    assert all(fn.is_ui for fn in functions)


def test_commonjs_assignment_export() -> None:
    source = """\
module.exports.greet = function greet(name) {
  return `hello ${name}`;
};
"""
    [fn] = extract_functions(source, "src/greet.js")
    assert fn.name == "greet"
    assert fn.exported is True


def test_declaration_files_and_unsupported_extensions_are_skipped() -> None:
    assert extract_functions("export function x() {}", "types/index.d.ts") == []
    assert extract_functions("print('hi')", "script.py") == []


def test_object_methods_on_unexported_objects_are_not_exported() -> None:
    source = """\
const helper = { run: () => 1, stop() { return 2; } };
"""
    functions = extract_functions(source, "src/helper.ts")
    assert {fn.name for fn in functions} == {"run", "stop"}
    assert all(fn.exported is False for fn in functions)


def test_mark_only_changed() -> None:
    functions = extract_functions(SOURCE, "src/math.ts")
    changed = mark_only_changed(functions, {1, 2, 9}, is_new_file=False, added_lines={2})
    assert {fn.name for fn in changed} == {"add", "multiply"}
    assert all(fn.is_new is False for fn in changed)


def test_mark_new_inserted_function() -> None:
    functions = extract_functions(SOURCE, "src/math.ts")
    changed = mark_only_changed(functions, {9}, is_new_file=False, added_lines={9})
    assert [fn.name for fn in changed] == ["multiply"]
    assert changed[0].is_new is True


def test_mark_all_changed_for_new_file() -> None:
    functions = extract_functions("export function a(){}\nexport function b(){}", "src/x.ts")
    changed = mark_only_changed(functions, set(), is_new_file=True)
    assert len(changed) == 2
    assert all(fn.is_new for fn in changed)
