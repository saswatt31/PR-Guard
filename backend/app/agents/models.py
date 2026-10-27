"""Typed models for generated tests and pipeline results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.coverage.gap import GapDecision
from app.coverage.istanbul import CoverageReport
from app.diff.models import DiffAnalysis, FunctionInfo


@dataclass
class TestProposal:
    file_path: str
    function_name: str
    source_file: str
    content: str
    framework: str = "vitest"
    reasoning: str = ""
    attempts: int = 0
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "function_name": self.function_name,
            "source_file": self.source_file,
            "content": self.content,
            "framework": self.framework,
            "reasoning": self.reasoning,
            "attempts": self.attempts,
            "last_error": self.last_error,
        }


@dataclass(frozen=True)
class RejectedTest:
    proposal: TestProposal
    reason: str


@dataclass
class PipelineResult:
    analysis: DiffAnalysis
    verified: list[TestProposal] = field(default_factory=list)
    rejected: list[RejectedTest] = field(default_factory=list)
    gaps: list[GapDecision] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    review: str | None = None
    coverage_before: CoverageReport | None = None
    coverage_after: CoverageReport | None = None
    coverage_delta: float | None = None
    cost: dict[str, int | float] = field(default_factory=dict)
    sandbox_results: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    attempts: int = 0

    @property
    def verified_count(self) -> int:
        return len(self.verified)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


@dataclass(frozen=True)
class GapTarget:
    """A serializable subset of a gap passed through graph state."""

    function: FunctionInfo
    reason: str
    existing_tests: tuple[str, ...] = ()
