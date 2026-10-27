from pathlib import Path

from app.diff.analyzer import analyze_diff


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def test_modified_file_only_returns_changed_functions(tmp_path: Path) -> None:
    write(
        tmp_path,
        "src/math.ts",
        """\
export function add(a: number, b: number) {
  return a + b;
}
export function sub(a: number, b: number) {
  return a - b;
}
""",
    )
    diff = """diff --git a/src/math.ts b/src/math.ts
--- a/src/math.ts
+++ b/src/math.ts
@@ -1,3 +1,3 @@
 export function add(a: number, b: number) {
-  return a + b;
+  return a + b + 0;
 }
"""
    analysis = analyze_diff(diff, tmp_path)
    assert [fn.name for fn in analysis.functions] == ["add"]
    assert analysis.files[0].changed_new_lines == {2}
    assert analysis.errors == []


def test_added_file_returns_all_functions(tmp_path: Path) -> None:
    write(
        tmp_path,
        "src/new.ts",
        "export const one = () => 1;\nexport function two() { return 2; }\n",
    )
    diff = """diff --git a/src/new.ts b/src/new.ts
new file mode 100644
--- /dev/null
+++ b/src/new.ts
@@ -0,0 +1,2 @@
+export const one = () => 1;
+export function two() { return 2; }
"""
    analysis = analyze_diff(diff, tmp_path)
    assert {fn.name for fn in analysis.functions} == {"one", "two"}
    assert all(fn.is_new for fn in analysis.functions)


def test_deleted_and_binary_files_are_not_extracted(tmp_path: Path) -> None:
    write(tmp_path, "src/old.ts", "export function gone() { return 1; }\n")
    diff = """diff --git a/src/old.ts b/src/old.ts
deleted file mode 100644
--- a/src/old.ts
+++ /dev/null
@@ -1 +0,0 @@
-export function gone() { return 1; }
diff --git a/logo.png b/logo.png
new file mode 100644
Binary files /dev/null and b/logo.png differ
"""
    analysis = analyze_diff(diff, tmp_path)
    assert analysis.functions == []
    assert analysis.files[0].status == "deleted"
    assert analysis.files[1].is_binary is True


def test_missing_file_and_unsafe_path_are_reported(tmp_path: Path) -> None:
    diff = """diff --git a/src/missing.ts b/src/missing.ts
--- a/src/missing.ts
+++ b/src/missing.ts
@@ -1 +1 @@
-a
+b
diff --git a/../evil.ts b/../evil.ts
--- a/../evil.ts
+++ b/../evil.ts
@@ -1 +1 @@
-a
+b
"""
    analysis = analyze_diff(diff, tmp_path)
    assert any("not found" in error for error in analysis.errors)
    assert any("escapes repository" in error or "unsafe" in error for error in analysis.errors)


def test_unsupported_file_is_ignored_without_error(tmp_path: Path) -> None:
    write(tmp_path, "README.md", "hello\n")
    diff = """diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-hello
+world
"""
    analysis = analyze_diff(diff, tmp_path)
    assert analysis.functions == []
    assert analysis.errors == []
