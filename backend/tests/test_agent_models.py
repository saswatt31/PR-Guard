"""Tests for agent result dataclasses."""

from __future__ import annotations

from app.agents.models import GapTarget, PipelineResult, RejectedTest
from app.agents.models import TestProposal as Proposal
from app.diff.models import DiffAnalysis, FunctionInfo


def proposal() -> Proposal:
    return Proposal(
        file_path="src/math.add.test.ts",
        function_name="add",
        source_file="src/math.ts",
        content="expect(1).toBe(1);",
        reasoning="covers add",
        attempts=2,
        last_error="boom",
    )


def test_test_proposal_to_dict_is_complete() -> None:
    assert proposal().to_dict() == {
        "file_path": "src/math.add.test.ts",
        "function_name": "add",
        "source_file": "src/math.ts",
        "content": "expect(1).toBe(1);",
        "framework": "vitest",
        "reasoning": "covers add",
        "attempts": 2,
        "last_error": "boom",
    }


def test_pipeline_result_counts_verified_and_rejected() -> None:
    item = proposal()
    result = PipelineResult(
        analysis=DiffAnalysis(),
        verified=[item],
        rejected=[RejectedTest(item, "failed")],
    )

    assert result.verified_count == 1
    assert result.rejected_count == 1
    assert result.errors == []
    assert result.attempts == 0


def test_gap_target_carries_function_and_reason() -> None:
    function = FunctionInfo(
        name="add",
        qualified_name="add",
        file_path="src/math.ts",
        signature="add(a, b)",
        source="function add(a, b) {}",
        start_line=1,
        end_line=1,
        exported=True,
    )
    target = GapTarget(function=function, reason="changed", existing_tests=("a.test.ts",))

    assert target.function is function
    assert target.reason == "changed"
    assert target.existing_tests == ("a.test.ts",)
