"""Tests for the generated-test static policy and safe file writing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.models import TestProposal as Proposal
from app.agents.safety import (
    MAX_TEST_CHARS,
    MAX_TEST_LINES,
    UnsafeTestError,
    suggest_test_path,
    unique_test_path,
    validate_proposal,
    validate_test_path,
    write_test_proposal,
)
from app.sandbox.errors import SandboxPolicyError


def proposal(
    *,
    file_path: str = "src/math.add.test.ts",
    function_name: str = "add",
    source_file: str = "src/math.ts",
    content: str | None = None,
    framework: str = "vitest",
    reasoning: str = "because",
) -> Proposal:
    return Proposal(
        file_path=file_path,
        function_name=function_name,
        source_file=source_file,
        content=content if content is not None else valid_content(),
        framework=framework,
        reasoning=reasoning,
    )


def valid_content(statement: str = "") -> str:
    return (
        'import { add } from "./math";\n'
        'import { describe, expect, it } from "vitest";\n'
        'describe("add", () => {\n'
        '  it("adds", () => {\n'
        f"    {statement}\n"
        "    expect(add(1, 2)).toBe(3);\n"
        "  });\n"
        "});\n"
    )


def content_with_import(specifier: str) -> str:
    return f'import thing from "{specifier}";\n' + valid_content()


@pytest.mark.parametrize(
    "source,name,expected",
    [
        ("src/math.ts", "add", "src/math.add.test.ts"),
        ("src/math.ts", "default", "src/math.test.ts"),
        ("src/widget.tsx", "default", "src/widget.test.tsx"),
        ("src/widget.jsx", "render", "src/widget.render.test.jsx"),
        ("src/text.md", "parse", "src/text.parse.test.ts"),
        ("index.ts", "main", "index.main.test.ts"),
        ("src/math.ts", "my-fn!", "src/math.my_fn.test.ts"),
        ("src/math.ts", "123abc", "src/math.fn_123abc.test.ts"),
        ("src/math.ts", "!!!", "src/math.function.test.ts"),
    ],
)
def test_suggest_test_path(source: str, name: str, expected: str) -> None:
    assert suggest_test_path(source, name) == expected


def test_unique_test_path_returns_preferred_when_free(tmp_path: Path) -> None:
    assert unique_test_path(tmp_path, "src/math.add.test.ts") == "src/math.add.test.ts"


def test_unique_test_path_avoids_existing_and_generated_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "math.add.test.ts").write_text("existing", encoding="utf-8")

    assert unique_test_path(tmp_path, "src/math.add.test.ts") == ("src/math.add.generated2.test.ts")

    (tmp_path / "src" / "math.add.generated2.test.ts").write_text("existing", encoding="utf-8")
    assert unique_test_path(tmp_path, "src/math.add.test.ts") == ("src/math.add.generated3.test.ts")


def test_unique_test_path_handles_spec_suffix(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "math.add.spec.ts").write_text("existing", encoding="utf-8")

    assert unique_test_path(tmp_path, "src/math.add.spec.ts") == ("src/math.add.generated2.spec.ts")


def test_unique_test_path_gives_up_after_many_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "exists", lambda self: True)

    with pytest.raises(UnsafeTestError, match="non-conflicting"):
        unique_test_path(tmp_path, "src/math.add.test.ts")


def test_validate_test_path_accepts_nested_relative_paths(tmp_path: Path) -> None:
    assert validate_test_path(tmp_path, "src\\nested\\a.test.ts", "src/a.ts") == (
        "src/nested/a.test.ts"
    )


@pytest.mark.parametrize(
    "test_path,source,message",
    [
        ("", "src/a.ts", "empty"),
        ("src/a\x00.test.ts", "src/a.ts", "NUL"),
        ("/src/a.test.ts", "src/a.ts", "relative"),
        ("../a.test.ts", "src/a.ts", "relative"),
        ("src/../a.test.ts", "src/a.ts", "relative"),
        ("src/a.ts", "src/a.ts", "must end with"),
        ("src/a.test.ts", "src/a.test.ts", "overwrite the source"),
    ],
)
def test_validate_test_path_rejects_unsafe_values(
    tmp_path: Path, test_path: str, source: str, message: str
) -> None:
    with pytest.raises(UnsafeTestError, match=message):
        validate_test_path(tmp_path, test_path, source)


def test_validate_proposal_normalizes_and_returns_a_copy(tmp_path: Path) -> None:
    original = proposal(
        file_path="src\\math.add.test.ts",
        source_file="./src/math.ts",
    )

    result = validate_proposal(
        tmp_path,
        original,
        expected_function="add",
        expected_source="src\\math.ts",
    )

    assert result is not original
    assert result.file_path == "src/math.add.test.ts"
    assert result.source_file == "src/math.ts"
    assert result.framework == "vitest"
    assert result.reasoning == "because"


def test_validate_proposal_rejects_source_and_function_mismatches(tmp_path: Path) -> None:
    with pytest.raises(UnsafeTestError, match="source file does not match"):
        validate_proposal(
            tmp_path,
            proposal(source_file="src/other.ts"),
            expected_function="add",
            expected_source="src/math.ts",
        )

    with pytest.raises(UnsafeTestError, match="function name does not match"):
        validate_proposal(
            tmp_path,
            proposal(function_name="sub"),
            expected_function="add",
            expected_source="src/math.ts",
        )


@pytest.mark.parametrize(
    "content,message",
    [
        ("   \n", "empty"),
        (valid_content() + "\x00", "NUL byte"),
        (valid_content() + "x" * MAX_TEST_CHARS, "exceeds"),
        ("\n".join(["it('x', () => expect(1).toBe(1));"] * (MAX_TEST_LINES + 1)), "exceeds"),
    ],
)
def test_validate_proposal_rejects_oversized_or_empty_content(
    tmp_path: Path, content: str, message: str
) -> None:
    with pytest.raises(UnsafeTestError, match=message):
        validate_proposal(
            tmp_path,
            proposal(content=content),
            expected_function="add",
            expected_source="src/math.ts",
        )


def test_validate_content_requires_it_and_expect(tmp_path: Path) -> None:
    with pytest.raises(UnsafeTestError, match="no it"):
        validate_proposal(
            tmp_path,
            proposal(content="expect(1).toBe(1);\n"),
            expected_function="add",
            expected_source="src/math.ts",
        )

    with pytest.raises(UnsafeTestError, match="no expect"):
        validate_proposal(
            tmp_path,
            proposal(content='it("runs", () => {});\n'),
            expected_function="add",
            expected_source="src/math.ts",
        )


@pytest.mark.parametrize(
    "statement",
    [
        'eval("2 + 2");',
        "new Function('return 1');",
        "process.env.SECRET;",
        "process.exit(1);",
        'require("fs");',
        'import("./other");',
    ],
)
def test_validate_content_rejects_forbidden_code(tmp_path: Path, statement: str) -> None:
    with pytest.raises(UnsafeTestError, match="forbidden code"):
        validate_proposal(
            tmp_path,
            proposal(content=valid_content(statement)),
            expected_function="add",
            expected_source="src/math.ts",
        )


@pytest.mark.parametrize(
    "specifier",
    [
        "fs",
        "node:fs",
        "node:fs/promises",
        "child_process",
        "node:child_process",
        "fs/promises",
        "node:http",
        "net",
        "node:vm",
    ],
)
def test_validate_content_rejects_forbidden_imports(tmp_path: Path, specifier: str) -> None:
    with pytest.raises(UnsafeTestError, match="forbidden module"):
        validate_proposal(
            tmp_path,
            proposal(content=content_with_import(specifier)),
            expected_function="add",
            expected_source="src/math.ts",
        )


def test_validate_content_rejects_relative_import_escape(tmp_path: Path) -> None:
    with pytest.raises(UnsafeTestError, match="escapes the repository"):
        validate_proposal(
            tmp_path,
            proposal(content=content_with_import("../../outside")),
            expected_function="add",
            expected_source="src/math.ts",
        )


def test_validate_content_rejects_unapproved_packages(tmp_path: Path) -> None:
    with pytest.raises(UnsafeTestError, match="unapproved package"):
        validate_proposal(
            tmp_path,
            proposal(content=content_with_import("axios")),
            expected_function="add",
            expected_source="src/math.ts",
        )


@pytest.mark.parametrize(
    "specifier",
    [
        "vitest/config",
        "@vitest/coverage-v8",
        "@testing-library/react",
        "@testing-library/user-event",
        "@playwright/test",
        "react",
    ],
)
def test_validate_content_allows_approved_packages(tmp_path: Path, specifier: str) -> None:
    result = validate_proposal(
        tmp_path,
        proposal(content=content_with_import(specifier)),
        expected_function="add",
        expected_source="src/math.ts",
    )

    assert result.file_path == "src/math.add.test.ts"


def test_write_test_proposal_creates_parent_directories(tmp_path: Path) -> None:
    target = write_test_proposal(
        tmp_path,
        proposal(file_path="src/deep/nested/math.add.test.ts"),
    )

    assert target == tmp_path / "src" / "deep" / "nested" / "math.add.test.ts"
    assert target.read_text(encoding="utf-8") == valid_content()


@pytest.mark.parametrize("file_path", ["../evil.test.ts", "../../evil.test.ts"])
def test_write_test_proposal_refuses_to_escape(tmp_path: Path, file_path: str) -> None:
    with pytest.raises(SandboxPolicyError, match="outside the repository"):
        write_test_proposal(tmp_path, proposal(file_path=file_path))


def test_write_test_proposal_refuses_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "src" / "math.add.test.ts"
    target.parent.mkdir(parents=True)
    target.write_text("user file", encoding="utf-8")
    monkeypatch.setattr(Path, "is_symlink", lambda self: True)

    with pytest.raises(SandboxPolicyError, match="symlink"):
        write_test_proposal(tmp_path, proposal())
