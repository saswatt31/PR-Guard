"""Typed models shared by the diff analyser and gap finder."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    section: str = ""


@dataclass
class FileDiff:
    path: str
    old_path: str
    status: str  # added | modified | deleted | renamed
    is_binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)
    added_lines: set[int] = field(default_factory=set)
    removed_lines: set[int] = field(default_factory=set)
    old_to_new: dict[int, int] = field(default_factory=dict)

    @property
    def changed_new_lines(self) -> set[int]:
        """New-file lines that were added or whose old counterpart was removed.

        Removed lines are mapped to the new line at the removal point. This can
        occasionally select an adjacent function when a deletion sits exactly between
        two functions; over-testing is preferred to missing a changed function.
        """

        if self.status == "added":
            return set(self.added_lines)
        mapped_removals = {self.old_to_new.get(old, 0) for old in self.removed_lines}
        return set(self.added_lines) | {line for line in mapped_removals if line > 0}


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    qualified_name: str
    file_path: str
    signature: str
    source: str
    start_line: int
    end_line: int
    exported: bool
    is_async: bool = False
    is_ui: bool = False
    container: str | None = None
    is_new: bool = False


@dataclass
class DiffAnalysis:
    files: list[FileDiff] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def changed_file_count(self) -> int:
        return len([f for f in self.files if f.status != "deleted" and not f.is_binary])
