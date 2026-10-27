"""Tests for the single PR comment renderer."""

from __future__ import annotations

from app.agents.models import PipelineResult, RejectedTest
from app.agents.models import TestProposal as Proposal
from app.comment import format_pr_comment
from app.coverage.istanbul import CoverageReport
from app.diff.models import DiffAnalysis, FileDiff


def result_with(
    *,
    verified: list[Proposal] | None = None,
    rejected: list[RejectedTest] | None = None,
    errors: list[str] | None = None,
    coverage_before: float | None = 50.0,
    coverage_after: float | None = 60.0,
) -> PipelineResult:
    analysis = DiffAnalysis(
        files=[FileDiff(path="src/math.ts", old_path="src/math.ts", status="modified")],
        functions=[],
    )
    return PipelineResult(
        analysis=analysis,
        verified=verified or [],
        rejected=rejected or [],
        gaps=[],
        errors=errors or [],
        coverage_before=(
            CoverageReport(line_pct=coverage_before) if coverage_before is not None else None
        ),
        coverage_after=(
            CoverageReport(line_pct=coverage_after) if coverage_after is not None else None
        ),
        coverage_delta=(
            round(coverage_after - coverage_before, 2)
            if coverage_before is not None and coverage_after is not None
            else None
        ),
        cost={"calls": 2, "input_tokens": 1200, "output_tokens": 300, "cost_usd": 0.0012},
    )


def proposal(path: str = "src/math.test.ts", content: str = "it('adds', () => {});") -> Proposal:
    return Proposal(
        file_path=path,
        function_name="add",
        source_file="src/math.ts",
        content=content,
    )


def test_comment_contains_only_verified_test_code() -> None:
    verified = proposal(content="it('works', () => expect(add(1, 2)).toBe(3));")
    rejected = RejectedTest(
        proposal("src/broken.test.ts", content="it('broken', () => { throw new Error(); });"),
        "sandbox test failed",
    )

    body = format_pr_comment("run-1", result_with(verified=[verified], rejected=[rejected]))

    assert "<!-- prguard:run:run-1 -->" in body
    assert "1 verified test" in body
    assert "it('works'" in body
    assert "it('broken'" not in body
    assert "sandbox test failed" in body
    assert "50.00% → 60.00% (+10.00 pp)" in body
    assert "2 calls" in body
    assert "$0.0012" in body


def test_comment_with_no_verified_tests_says_none() -> None:
    body = format_pr_comment("run-2", result_with(coverage_before=None, coverage_after=None))

    assert "0 verified tests" in body
    assert "### Verified tests\n_None._" in body
    assert "not measured" in body


def test_comment_lists_warnings_and_caps_them() -> None:
    body = format_pr_comment(
        "run-3",
        result_with(errors=[f"warning {index}" for index in range(8)]),
    )

    assert "### Warnings" in body
    assert "warning 4" in body
    assert "warning 5" not in body
    assert "3 more not shown" in body


def test_comment_mentions_when_no_gaps_were_found() -> None:
    body = format_pr_comment("run-4", result_with())

    assert "No untested changed functions were found." in body


def test_comment_escapes_backticks_in_paths() -> None:
    body = format_pr_comment(
        "run-5",
        result_with(verified=[proposal(path="src/weird`name.test.ts")]),
    )

    assert "src/weird'name.test.ts" in body
    assert "<code>src/weird`name.test.ts</code>" not in body


def test_comment_drops_tests_that_do_not_fit_the_limit() -> None:
    verified = [proposal(f"src/test-{index}.test.ts", content="x" * 500) for index in range(5)]

    body = format_pr_comment("run-6", result_with(verified=verified), max_chars=2000)

    assert len(body) <= 2000
    assert "verified test(s) omitted" in body
