from app.diff.parser import parse_diff

MODIFIED = """diff --git a/src/math.ts b/src/math.ts
index 1111111..2222222 100644
--- a/src/math.ts
+++ b/src/math.ts
@@ -3,4 +3,4 @@
 export function sub(a: number, b: number) {
-  return a - b;
+  return a - b - 0;
 }
@@ -9,3 +9,4 @@
 export function add(a: number, b: number) {
-  return a + b;
+  const total = a + b;
+  return total;
 }
"""


def test_modified_file_hunks_and_changed_lines() -> None:
    [file] = parse_diff(MODIFIED)
    assert file.path == "src/math.ts"
    assert file.old_path == "src/math.ts"
    assert file.status == "modified"
    assert len(file.hunks) == 2
    assert file.hunks[0].old_start == 3
    assert file.hunks[1].old_start == 9
    assert file.added_lines == {4, 10, 11}
    assert file.removed_lines == {4, 10}
    assert file.changed_new_lines == {4, 10, 11}


def test_added_file_has_all_lines_changed() -> None:
    diff = """diff --git a/src/new.ts b/src/new.ts
new file mode 100644
--- /dev/null
+++ b/src/new.ts
@@ -0,0 +1,2 @@
+export const x = 1;
+export const y = 2;
"""
    [file] = parse_diff(diff)
    assert file.status == "added"
    assert file.path == "src/new.ts"
    assert file.old_path == "src/new.ts"
    assert file.added_lines == {1, 2}
    assert file.changed_new_lines == {1, 2}


def test_deleted_file_keeps_old_path() -> None:
    diff = """diff --git a/src/old.ts b/src/old.ts
deleted file mode 100644
--- a/src/old.ts
+++ /dev/null
@@ -1,2 +0,0 @@
-export const gone = 1;
-export const alsoGone = 2;
"""
    [file] = parse_diff(diff)
    assert file.status == "deleted"
    assert file.path == "src/old.ts"
    assert file.removed_lines == {1, 2}


def test_rename_without_content_changes() -> None:
    diff = """diff --git a/src/a.ts b/src/b.ts
similarity index 100%
rename from src/a.ts
rename to src/b.ts
"""
    [file] = parse_diff(diff)
    assert file.status == "renamed"
    assert file.old_path == "src/a.ts"
    assert file.path == "src/b.ts"
    assert file.changed_new_lines == set()


def test_binary_file_is_flagged_and_path_parsed_from_header() -> None:
    diff = """diff --git a/assets/logo.png b/assets/logo.png
new file mode 100644
Binary files /dev/null and b/assets/logo.png differ
"""
    [file] = parse_diff(diff)
    assert file.is_binary is True
    assert file.path == "assets/logo.png"
    assert file.hunks == []


def test_quoted_paths_with_spaces() -> None:
    diff = """diff --git "a/src/a b.ts" "b/src/a b.ts"
--- "a/src/a b.ts"
+++ "b/src/a b.ts"
@@ -1 +1 @@
-old
+new
"""
    [file] = parse_diff(diff)
    assert file.path == "src/a b.ts"
    assert file.old_path == "src/a b.ts"


def test_multiple_files_and_crlf() -> None:
    diff = (
        MODIFIED.replace("\n", "\r\n")
        + """diff --git a/docs/readme.md b/docs/readme.md
--- a/docs/readme.md
+++ b/docs/readme.md
@@ -1 +1 @@
-old
+new
"""
    )
    files = parse_diff(diff)
    assert [f.path for f in files] == ["src/math.ts", "docs/readme.md"]


def test_no_newline_marker_is_ignored() -> None:
    diff = """diff --git a/a.ts b/a.ts
--- a/a.ts
+++ b/a.ts
@@ -1 +1 @@
-old
+new
\\ No newline at end of file
"""
    [file] = parse_diff(diff)
    assert file.added_lines == {1}
    assert file.removed_lines == {1}


def test_malformed_hunk_is_ignored() -> None:
    diff = """diff --git a/a.ts b/a.ts
--- a/a.ts
+++ b/a.ts
@@ this is not a hunk @@
+ignored
"""
    [file] = parse_diff(diff)
    assert file.hunks == []
    assert file.added_lines == set()


def test_empty_diff() -> None:
    assert parse_diff("") == []
