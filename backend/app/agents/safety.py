"""Static checks applied to LLM-written test code before it reaches the sandbox.

This is *not* the security boundary; the Docker sandbox is. It catches obvious mistakes
and dangerous imports early, keeps generated files inside the repository, and prevents a
test from overwriting application source or an existing user test.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path, PurePosixPath

from app.agents.models import TestProposal
from app.sandbox.errors import SandboxPolicyError

TEST_SUFFIXES = (
    ".test.ts",
    ".test.tsx",
    ".test.js",
    ".test.jsx",
    ".test.mts",
    ".test.cts",
    ".spec.ts",
    ".spec.tsx",
    ".spec.js",
    ".spec.jsx",
)
SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"}
MAX_TEST_CHARS = 30_000
MAX_TEST_LINES = 600
ALLOWED_PACKAGES = {
    "vitest",
    "@vitest/coverage-v8",
    "@testing-library/react",
    "@testing-library/jest-dom",
    "@testing-library/user-event",
    "react",
    "react-dom",
    "playwright",
    "@playwright/test",
}
FORBIDDEN_MODULES = {
    "child_process",
    "node:child_process",
    "fs",
    "node:fs",
    "node:fs/promises",
    "http",
    "node:http",
    "https",
    "node:https",
    "net",
    "node:net",
    "dgram",
    "node:dgram",
    "vm",
    "node:vm",
    "worker_threads",
    "node:worker_threads",
}
FORBIDDEN_CODE = (
    re.compile(r"\beval\s*\("),
    re.compile(r"\bnew\s+Function\s*\("),
    re.compile(r"\bprocess\s*\.\s*env\b"),
    re.compile(r"\bprocess\s*\.\s*exit\b"),
    re.compile(r"\brequire\s*\("),
    re.compile(r"\bimport\s*\("),
)
IMPORT_RE = re.compile(
    r"""\bimport\s+(?:(?:[^'"]*?\s+from\s+)?)["']([^"']+)["']""",
)


class UnsafeTestError(ValueError):
    """A generated test violates the static policy."""


def suggest_test_path(source_file: str, function_name: str) -> str:
    source = PurePosixPath(source_file)
    suffix = source.suffix if source.suffix in SOURCE_SUFFIXES else ".ts"
    if function_name == "default":
        return (source.parent / f"{source.stem}.test{suffix}").as_posix()
    safe_name = re.sub(r"[^A-Za-z0-9_$]+", "_", function_name).strip("_") or "function"
    if safe_name[0].isdigit():
        safe_name = f"fn_{safe_name}"
    return (source.parent / f"{source.stem}.{safe_name}.test{suffix}").as_posix()


def unique_test_path(root: Path, preferred: str) -> str:
    """Avoid overwriting an existing user test or another generated proposal."""

    path = PurePosixPath(preferred)
    candidate = root / path
    if not candidate.exists():
        return path.as_posix()
    name = path.name
    for suffix in TEST_SUFFIXES:
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            extension = suffix
            break
    else:  # pragma: no cover - validated callers only pass test suffixes
        base, extension = path.stem, path.suffix
    for index in range(2, 50):
        alternative = path.with_name(f"{base}.generated{index}{extension}")
        if not (root / alternative).exists():
            return alternative.as_posix()
    raise UnsafeTestError("could not find a non-conflicting test path")


def validate_test_path(root: Path, test_path: str, source_file: str) -> str:
    if not test_path or "\x00" in test_path:
        raise UnsafeTestError("test path is empty or contains NUL")
    pure = PurePosixPath(test_path.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise UnsafeTestError("test path must be relative and inside the repository")
    if not pure.name.endswith(TEST_SUFFIXES):
        raise UnsafeTestError(f"test path must end with one of {TEST_SUFFIXES}")
    if pure.as_posix() == PurePosixPath(source_file).as_posix():
        raise UnsafeTestError("test path must not overwrite the source file")
    resolved_root = root.resolve()
    resolved = (resolved_root / pure).resolve()
    if resolved_root not in resolved.parents:
        raise UnsafeTestError("test path escapes the repository")
    return pure.as_posix()


def validate_proposal(
    root: Path,
    proposal: TestProposal,
    *,
    expected_function: str,
    expected_source: str,
) -> TestProposal:
    expected_source = PurePosixPath(expected_source.replace("\\", "/")).as_posix()
    source = PurePosixPath(proposal.source_file.replace("\\", "/")).as_posix()
    if source.lstrip("./") != expected_source.lstrip("./"):
        raise UnsafeTestError("proposal source file does not match the gap")
    if proposal.function_name != expected_function:
        raise UnsafeTestError("proposal function name does not match the gap")
    path = validate_test_path(root, proposal.file_path, expected_source)
    content = proposal.content
    if not content.strip():
        raise UnsafeTestError("generated test is empty")
    if len(content) > MAX_TEST_CHARS:
        raise UnsafeTestError(f"generated test exceeds {MAX_TEST_CHARS} characters")
    if len(content.splitlines()) > MAX_TEST_LINES:
        raise UnsafeTestError(f"generated test exceeds {MAX_TEST_LINES} lines")
    if "\x00" in content:
        raise UnsafeTestError("generated test contains a NUL byte")
    _validate_content(path, content)
    return TestProposal(
        file_path=path,
        function_name=proposal.function_name,
        source_file=source,
        content=content,
        framework=proposal.framework,
        reasoning=proposal.reasoning,
    )


def _validate_content(test_path: str, content: str) -> None:
    if not re.search(r"\b(?:it|test)\s*(?:\.\w+)?\s*\(", content):
        raise UnsafeTestError("generated test contains no it()/test() block")
    if not re.search(r"\bexpect\s*\(", content):
        raise UnsafeTestError("generated test contains no expect() assertion")
    for pattern in FORBIDDEN_CODE:
        if pattern.search(content):
            raise UnsafeTestError(f"generated test contains forbidden code: {pattern.pattern}")
    parent = PurePosixPath(test_path).parent
    for specifier in IMPORT_RE.findall(content):
        if specifier in FORBIDDEN_MODULES or specifier.startswith(
            ("fs/", "node:fs/", "child_process/", "node:child_process/")
        ):
            raise UnsafeTestError(f"generated test imports forbidden module: {specifier}")
        if specifier.startswith("."):
            resolved = posixpath.normpath(str(parent / specifier))
            if resolved.startswith("../") or resolved == ".." or resolved.startswith("/"):
                raise UnsafeTestError(f"relative import escapes the repository: {specifier}")
            continue
        if specifier not in ALLOWED_PACKAGES and not specifier.startswith(
            ("vitest/", "@vitest/", "@testing-library/", "@playwright/")
        ):
            raise UnsafeTestError(f"generated test imports an unapproved package: {specifier}")


def write_test_proposal(root: Path, proposal: TestProposal) -> Path:
    root = root.resolve()
    target = (root / PurePosixPath(proposal.file_path)).resolve()
    if root not in target.parents:
        raise SandboxPolicyError("refusing to write a test outside the repository")
    if target.exists() and target.is_symlink():
        raise SandboxPolicyError("refusing to overwrite a symlink with a generated test")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(proposal.content, encoding="utf-8")
    return target
