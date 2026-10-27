"""Unified diff parser.

Only what the agent needs: per-file status, hunk locations, and the exact new-file
lines that changed. Handles git's quoted paths, binary files, renames and CRLF.
"""

from __future__ import annotations

import json
import re
import shlex

from app.diff.models import FileDiff, Hunk

HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@ ?(?P<section>.*)$"
)


def _clean_path(raw: str) -> str:
    value = raw.strip().split("\t", 1)[0]
    if value.startswith('"') and value.endswith('"'):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = value[1:-1]
    if value.startswith(("a/", "b/")):
        value = value[2:]
    return value


def parse_diff(diff_text: str) -> list[FileDiff]:
    lines = diff_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    files: list[FileDiff] = []
    current: FileDiff | None = None
    index = 0

    while index < len(lines):
        line = lines[index]

        if line.startswith("diff --git "):
            if current is not None:
                files.append(_finalize(current))
            current = FileDiff(path="", old_path="", status="modified")
            old_path, new_path = _header_paths(line)
            current.old_path = old_path
            current.path = new_path
            index += 1
            continue

        if current is None:
            index += 1
            continue

        if line.startswith("new file mode"):
            current.status = "added"
        elif line.startswith("deleted file mode"):
            current.status = "deleted"
        elif line.startswith("rename from "):
            current.old_path = _clean_path(line[len("rename from ") :])
            current.status = "renamed"
        elif line.startswith("rename to "):
            current.path = _clean_path(line[len("rename to ") :])
            current.status = "renamed"
        elif line.startswith("--- "):
            current.old_path = _clean_path(line[4:])
        elif line.startswith("+++ "):
            new_path = _clean_path(line[4:])
            if new_path != "/dev/null":
                current.path = new_path
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            current.is_binary = True
        elif line.startswith("@@"):
            match = HUNK_RE.match(line)
            if not match:
                index += 1
                continue
            old_start = int(match.group("old_start"))
            old_count = int(match.group("old_count") or "1")
            new_start = int(match.group("new_start"))
            new_count = int(match.group("new_count") or "1")
            current.hunks.append(
                Hunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    section=(match.group("section") or "").strip(),
                )
            )
            index = _consume_hunk(lines, index + 1, current, old_start, new_start)
            continue

        index += 1

    if current is not None:
        files.append(_finalize(current))
    return [file for file in files if file.path or file.old_path]


def _consume_hunk(
    lines: list[str], index: int, current: FileDiff, old_line: int, new_line: int
) -> int:
    while index < len(lines):
        content = lines[index]
        if content.startswith("diff --git ") or content.startswith("@@"):
            break
        if content.startswith("\\ No newline"):
            index += 1
            continue
        if not content:
            # A truly empty line in a diff means a blank context line whose leading
            # space was lost by tooling; treat it as context.
            current.old_to_new[old_line] = new_line
            old_line += 1
            new_line += 1
            index += 1
            continue
        prefix = content[0]
        if prefix == "+":
            current.added_lines.add(new_line)
            new_line += 1
        elif prefix == "-":
            current.removed_lines.add(old_line)
            current.old_to_new[old_line] = new_line
            old_line += 1
        elif prefix == " ":
            current.old_to_new[old_line] = new_line
            old_line += 1
            new_line += 1
        else:
            # Malformed hunk content; stop and let the outer loop resynchronise.
            break
        index += 1
    return index


def _finalize(file: FileDiff) -> FileDiff:
    if not file.path:
        file.path = file.old_path
    if not file.old_path:
        file.old_path = file.path
    if file.path == "/dev/null":
        file.path = file.old_path
    if file.old_path == "/dev/null":
        file.old_path = file.path
    return file


def _header_paths(line: str) -> tuple[str, str]:
    """Best-effort paths from ``diff --git a/x b/y`` (used for binary diffs)."""

    rest = line[len("diff --git ") :].strip()
    if rest.startswith('"'):
        try:
            parts = shlex.split(rest)
        except ValueError:
            parts = []
        if len(parts) == 2:
            return _clean_path(parts[0]), _clean_path(parts[1])
    if " b/" in rest:
        left, right = rest.rsplit(" b/", 1)
        return _clean_path(left), _clean_path(right)
    return "", ""
