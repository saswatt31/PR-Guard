"""End-to-end tests for the LangGraph agent pipeline using a fake sandbox."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.graph import (
    AgentDependencies,
    _add_error,
    _dedupe,
    _load_coverage,
    run_agent_pipeline,
)
from app.agents.models import TestProposal as Proposal
from app.config.repo import RepoConfig
from app.coverage.istanbul import CoverageReport
from app.diff.analyzer import analyze_diff
from app.llm.base import LLMError
from app.llm.budget import BudgetedLLM
from app.llm.fake import FakeLLM
from app.sandbox.models import SandboxResult, SandboxStatus
from app.settings import Settings

MATH = """\
export function add(a: number, b: number) {
  return a + b;
}
"""

MATH_TEST = """\
import { expect, it } from "vitest";
import { add } from "./math";

it("adds", () => expect(add(1, 2)).toBe(3));
"""

DIFF = """\
diff --git a/src/math.ts b/src/math.ts
--- a/src/math.ts
+++ b/src/math.ts
@@ -1,3 +1,3 @@
 export function add(a: number, b: number) {
-  return a + b;
+  return a + b + 0;
 }
"""

OPS = """\
export function one() { return 1; }
export function two() { return 2; }
export function three() { return 3; }
"""

OPS_DIFF = """\
diff --git a/src/ops.ts b/src/ops.ts
new file mode 100644
--- /dev/null
+++ b/src/ops.ts
@@ -0,0 +1,3 @@
+export function one() { return 1; }
+export function two() { return 2; }
+export function three() { return 3; }
"""

BUTTON = """\
export function Button() {
  return <button>Save</button>;
}
"""

BUTTON_DIFF = """\
diff --git a/src/button.tsx b/src/button.tsx
new file mode 100644
--- /dev/null
+++ b/src/button.tsx
@@ -0,0 +1,3 @@
+export function Button() {
+  return <button>Save</button>;
+}
"""


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def write_json(root: Path, path: str, data: object) -> None:
    write(root, path, json.dumps(data))


def sandbox_result(
    phase: str,
    status: SandboxStatus | str = SandboxStatus.PASSED,
    *,
    stdout: str = "",
    stderr: str = "",
    error: str | None = None,
) -> SandboxResult:
    status_value = str(status)
    return SandboxResult(
        phase=phase,
        command=("fake",),
        status=status_value,
        exit_code=0 if status_value == "passed" else 1,
        timed_out=status_value == "timeout",
        duration_ms=1,
        stdout=stdout,
        stderr=stderr,
        network_disabled=phase == "test",
        isolation="fake",
        error=error,
    )


class FakeSandbox:
    def __init__(self, test_outcomes: list[Any] | None = None, install_outcome: Any = None) -> None:
        self.test_outcomes = list(test_outcomes or [])
        self.install_outcome = install_outcome or (lambda root, command: sandbox_result("install"))
        self.calls: list[dict[str, Any]] = []

    def run(
        self,
        root: Path,
        command: list[str],
        *,
        phase: str,
        network_disabled: bool,
        timeout_seconds: int,
        labels: dict[str, str] | None = None,
    ) -> SandboxResult:
        self.calls.append(
            {
                "phase": phase,
                "command": tuple(command),
                "network_disabled": network_disabled,
                "timeout_seconds": timeout_seconds,
                "labels": labels,
            }
        )
        if phase == "install":
            return _resolve(self.install_outcome, root, command)
        outcome = self.test_outcomes.pop(0) if self.test_outcomes else sandbox_result("test")
        return _resolve(outcome, root, command)


def _resolve(outcome: Any, root: Path, command: list[str]) -> SandboxResult:
    if callable(outcome):
        return outcome(root, command)
    return outcome


def coverage_payload(
    *,
    file: str = "src/math.ts",
    name: str = "add",
    hits: int = 1,
    start: int = 1,
    end: int = 3,
    line_pct: float = 60.0,
) -> dict[str, object]:
    return {
        file: {
            "fnMap": {
                "0": {
                    "name": name,
                    "decl": {"start": {"line": start}, "end": {"line": end}},
                }
            },
            "f": {"0": hits},
        },
        "total": {"lines": {"pct": line_pct}},
    }


def passing_outcome(
    *,
    name: str = "src/math.add.test.ts",
    coverage_name: str = "add",
    hits: int = 1,
    line_pct: float = 60.0,
) -> Any:
    def run(root: Path, command: list[str]) -> SandboxResult:
        write_json(
            root,
            "vitest-results.json",
            {
                "testResults": [
                    {
                        "name": name,
                        "status": "passed",
                        "assertionResults": [{"title": "runs", "status": "passed"}],
                    }
                ]
            },
        )
        write_json(
            root,
            "coverage/coverage-final.json",
            coverage_payload(name=coverage_name, hits=hits, line_pct=line_pct),
        )
        return sandbox_result("test")

    return run


def failing_outcome(message: str = "expected 3 to be 4") -> Any:
    def run(root: Path, command: list[str]) -> SandboxResult:
        write_json(
            root,
            "vitest-results.json",
            {
                "testResults": [
                    {
                        "name": "src/math.add.test.ts",
                        "status": "failed",
                        "assertionResults": [
                            {
                                "title": "runs",
                                "status": "failed",
                                "failureMessages": message,
                            }
                        ],
                    }
                ]
            },
        )
        return sandbox_result("test", SandboxStatus.FAILED, stderr=message)

    return run


def make_test_content(statement: str = "expect(add(1, 2)).toBe(3);") -> str:
    return (
        'import { add } from "./math";\n'
        'import { describe, expect, it } from "vitest";\n'
        "\n"
        'describe("add", () => {\n'
        '  it("runs", () => {\n'
        f"    {statement}\n"
        "  });\n"
        "});\n"
    )


def proposal_json(
    *,
    function: str = "add",
    source: str = "src/math.ts",
    file_path: str = "src/math.add.test.ts",
    content: str | None = None,
    framework: str = "vitest",
) -> str:
    return json.dumps(
        {
            "proposals": [
                {
                    "file_path": file_path,
                    "function_name": function,
                    "source_file": source,
                    "content": content if content is not None else make_test_content(),
                    "framework": framework,
                    "reasoning": "test",
                }
            ]
        }
    )


def budgeted(
    responses: list[Any] | None = None,
    *,
    max_calls: int = 24,
    max_total_tokens: int = 120_000,
    max_cost_usd: float = 0.75,
) -> BudgetedLLM:
    return BudgetedLLM(
        FakeLLM(responses),
        max_calls=max_calls,
        max_total_tokens=max_total_tokens,
        max_cost_usd=max_cost_usd,
    )


def dependencies(
    tmp_path: Path,
    settings: Settings,
    sandbox: FakeSandbox,
    *,
    llm: BudgetedLLM | None = None,
    config: RepoConfig | None = None,
    coverage_before: CoverageReport | None = None,
) -> AgentDependencies:
    return AgentDependencies(
        settings=settings,
        config=config or RepoConfig(),
        llm=llm or budgeted(),
        sandbox=sandbox,
        repo_root=tmp_path,
        coverage_before=coverage_before,
        run_id="run-1",
    )


def raising(messages: list[dict[str, str]]) -> str:
    raise LLMError("provider down")


async def test_pipeline_verifies_generated_test_and_tracks_coverage(
    tmp_path: Path, settings: Settings
) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox([passing_outcome()])
    deps = dependencies(
        tmp_path,
        settings,
        sandbox,
        coverage_before=CoverageReport(line_pct=50.0),
    )

    result = await run_agent_pipeline(deps, DIFF)

    assert result.verified_count == 1
    assert result.rejected_count == 0
    assert result.attempts == 0
    assert result.errors == []
    assert result.verified[0].file_path == "src/math.add.test.ts"
    written = (tmp_path / "src/math.add.test.ts").read_text(encoding="utf-8")
    assert written == result.verified[0].content
    assert 'import { add } from "./math";' in written
    assert "expect(result).toBe(result);" in written
    assert result.coverage_after is not None
    assert result.coverage_after.line_pct == 60.0
    assert result.coverage_delta == 10.0
    assert result.review is not None and "FakeLLM review" in result.review
    assert result.cost["calls"] == 2
    assert [step["node"] for step in result.steps] == [
        "analyze",
        "find_gaps",
        "write",
        "execute",
        "review",
    ]
    assert all(step["status"] == "succeeded" for step in result.steps)
    assert result.steps[0]["detail"]["functions"] == 1
    assert len(result.gaps) == 1
    assert [call["phase"] for call in sandbox.calls] == ["install", "test"]
    assert sandbox.calls[0]["network_disabled"] is False
    assert sandbox.calls[1]["network_disabled"] is True
    assert sandbox.calls[0]["labels"] == {"run_id": "run-1"}
    assert sandbox.calls[0]["timeout_seconds"] == settings.sandbox_install_timeout_seconds
    assert sandbox.calls[1]["timeout_seconds"] == settings.sandbox_timeout_seconds
    assert len(result.sandbox_results) == 2
    assert result.sandbox_results[0]["phase"] == "install"


async def test_pipeline_reuses_precomputed_analysis_and_baseline_install(
    tmp_path: Path, settings: Settings
) -> None:
    write(tmp_path, "src/math.ts", MATH)
    analysis = analyze_diff(DIFF, tmp_path)
    sandbox = FakeSandbox([passing_outcome()])
    deps = dependencies(tmp_path, settings, sandbox)
    deps.initial_analysis = analysis
    deps.dependencies_installed = True

    result = await run_agent_pipeline(deps, DIFF)

    assert [call["phase"] for call in sandbox.calls] == ["test"]
    assert result.steps[0]["detail"]["functions"] == 1
    assert result.verified_count == 1


async def test_pipeline_reviews_without_writing_when_no_gaps(
    tmp_path: Path, settings: Settings
) -> None:
    write(tmp_path, "src/math.ts", MATH)
    write(tmp_path, "src/math.test.ts", MATH_TEST)
    sandbox = FakeSandbox()

    result = await run_agent_pipeline(dependencies(tmp_path, settings, sandbox), DIFF)

    assert result.verified == []
    assert result.rejected == []
    assert sandbox.calls == []
    assert result.cost["calls"] == 1
    assert result.review is not None and "FakeLLM review" in result.review
    assert result.coverage_delta is None


async def test_pipeline_skips_review_when_disabled(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/math.ts", MATH)
    write(tmp_path, "src/math.test.ts", MATH_TEST)
    sandbox = FakeSandbox()

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            config=RepoConfig(review_code=False),
        ),
        DIFF,
    )

    assert result.review is None
    assert result.cost["calls"] == 0
    assert sandbox.calls == []


async def test_long_review_is_truncated(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/math.ts", MATH)
    write(tmp_path, "src/math.test.ts", MATH_TEST)
    sandbox = FakeSandbox()

    result = await run_agent_pipeline(
        dependencies(tmp_path, settings, sandbox, llm=budgeted(["R" * 9000])),
        DIFF,
    )

    assert result.review is not None
    assert len(result.review) == 8000


async def test_install_failure_rejects_drafts_and_skips_tests(
    tmp_path: Path, settings: Settings
) -> None:
    write(tmp_path, "src/math.ts", MATH)
    install_failure = sandbox_result("install", SandboxStatus.FAILED, stderr="npm ERR! network")
    sandbox = FakeSandbox(install_outcome=install_failure)

    result = await run_agent_pipeline(dependencies(tmp_path, settings, sandbox), DIFF)

    assert result.verified == []
    assert result.rejected_count == 1
    assert "dependency install failed: npm ERR! network" in result.rejected[0].reason
    assert any("sandbox install failed" in error for error in result.errors)
    assert [call["phase"] for call in sandbox.calls] == ["install"]
    assert result.cost["calls"] == 2
    assert result.attempts == 0


async def test_fixer_repairs_a_failing_test_and_installs_once(
    tmp_path: Path, settings: Settings
) -> None:
    write(tmp_path, "src/math.ts", MATH)
    fixed = make_test_content("expect(add(1, 2)).toBe(4);")
    sandbox = FakeSandbox([failing_outcome(), passing_outcome()])
    llm = budgeted(
        [
            proposal_json(),
            proposal_json(content=fixed),
            "Reviewed by the fake model.",
        ]
    )

    result = await run_agent_pipeline(dependencies(tmp_path, settings, sandbox, llm=llm), DIFF)

    assert result.verified_count == 1
    assert result.rejected_count == 0
    assert result.attempts == 1
    assert result.verified[0].attempts == 1
    assert (tmp_path / "src/math.add.test.ts").read_text(encoding="utf-8") == fixed
    assert [call["phase"] for call in sandbox.calls] == ["install", "test", "test"]
    assert result.cost["calls"] == 3
    assert result.review == "Reviewed by the fake model."
    assert [step["node"] for step in result.steps] == [
        "analyze",
        "find_gaps",
        "write",
        "execute",
        "fix",
        "execute",
        "review",
    ]
    assert result.steps[4]["status"] == "succeeded"


async def test_pipeline_stops_after_max_fix_attempts(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox([failing_outcome() for _ in range(10)])

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            config=RepoConfig(max_fix_attempts=1),
        ),
        DIFF,
    )

    assert result.verified == []
    assert result.rejected_count == 1
    assert result.attempts == 1
    assert "expected 3 to be 4" in result.rejected[0].reason
    assert [call["phase"] for call in sandbox.calls] == ["install", "test", "test"]
    assert result.cost["calls"] == 3


async def test_zero_fix_attempts_rejects_immediately(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox([failing_outcome()])

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            config=RepoConfig(max_fix_attempts=0),
        ),
        DIFF,
    )

    assert result.rejected_count == 1
    assert result.attempts == 0
    assert [call["phase"] for call in sandbox.calls] == ["install", "test"]
    assert result.cost["calls"] == 2


async def test_coverage_zero_hits_rejects_a_passing_test(
    tmp_path: Path, settings: Settings
) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox([passing_outcome(hits=0)])

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            config=RepoConfig(max_fix_attempts=0),
        ),
        DIFF,
    )

    assert result.verified == []
    assert result.rejected_count == 1
    assert "coverage shows 0 executions" in result.rejected[0].reason
    assert result.coverage_after is not None
    assert result.coverage_after.function_hits("src/math.ts", "add", 1, 3) == 0


async def test_coverage_without_the_target_function_accepts_the_test(
    tmp_path: Path, settings: Settings
) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox([passing_outcome(coverage_name="somethingElse")])

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            config=RepoConfig(max_fix_attempts=0),
            coverage_before=CoverageReport(line_pct=55.0),
        ),
        DIFF,
    )

    assert result.verified_count == 1
    assert result.coverage_after is not None
    assert result.coverage_delta == 5.0


async def test_test_missing_from_the_report_is_rejected(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox([passing_outcome(name="src/other.test.ts")])

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            config=RepoConfig(max_fix_attempts=0),
        ),
        DIFF,
    )

    assert result.rejected_count == 1
    assert "missing from the Vitest report" in result.rejected[0].reason


async def test_exit_status_is_used_when_the_report_is_missing(
    tmp_path: Path, settings: Settings
) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox([sandbox_result("test")])

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            config=RepoConfig(max_fix_attempts=0),
        ),
        DIFF,
    )

    assert result.verified_count == 1
    assert result.coverage_after is None


async def test_stale_outputs_are_removed_before_the_test_phase(
    tmp_path: Path, settings: Settings
) -> None:
    write(tmp_path, "src/math.ts", MATH)
    write_json(
        tmp_path,
        "vitest-results.json",
        {
            "testResults": [
                {
                    "name": "src/math.add.test.ts",
                    "assertionResults": [{"status": "passed", "title": "stale"}],
                }
            ]
        },
    )
    write_json(tmp_path, "coverage/coverage-final.json", coverage_payload())
    sandbox = FakeSandbox([sandbox_result("test", SandboxStatus.FAILED, stderr="boom")])

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            config=RepoConfig(max_fix_attempts=0),
        ),
        DIFF,
    )

    assert result.verified == []
    assert result.rejected_count == 1
    assert result.rejected[0].reason == "boom"
    assert not (tmp_path / "vitest-results.json").exists()
    assert not (tmp_path / "coverage/coverage-final.json").exists()


async def test_timeout_is_reported_and_draft_is_rejected(
    tmp_path: Path, settings: Settings
) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox([sandbox_result("test", SandboxStatus.TIMEOUT)])

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            config=RepoConfig(max_fix_attempts=0),
        ),
        DIFF,
    )

    assert result.rejected_count == 1
    assert result.rejected[0].reason == "test failed"
    assert any("sandbox test phase timeout" in error for error in result.errors)
    assert any("test phase timed out" in error for error in result.errors)


async def test_writer_llm_error_is_recorded(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox()

    result = await run_agent_pipeline(
        dependencies(tmp_path, settings, sandbox, llm=budgeted([raising])),
        DIFF,
    )

    assert result.verified == []
    assert any("writer failed for add" in error for error in result.errors)
    assert sandbox.calls == []
    assert result.cost["calls"] == 1


async def test_writer_invalid_json_is_rejected(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox()

    result = await run_agent_pipeline(
        dependencies(tmp_path, settings, sandbox, llm=budgeted(["not json"])),
        DIFF,
    )

    assert result.verified == []
    assert any("writer output rejected" in error for error in result.errors)
    assert sandbox.calls == []


async def test_writer_playwright_proposal_is_rejected(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox()

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            llm=budgeted([proposal_json(framework="playwright")]),
        ),
        DIFF,
    )

    assert any("only Vitest" in error for error in result.errors)
    assert sandbox.calls == []


async def test_writer_cannot_overwrite_an_existing_test(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/math.ts", MATH)
    write(tmp_path, "src/math.test.ts", 'it("placeholder", () => expect(true).toBe(true));\n')
    sandbox = FakeSandbox()

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            llm=budgeted([proposal_json(file_path="src/math.test.ts")]),
        ),
        DIFF,
    )

    assert any("would overwrite an existing test" in error for error in result.errors)
    assert sandbox.calls == []


async def test_writer_unsafe_content_is_rejected(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox()

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            llm=budgeted(
                [
                    proposal_json(
                        content=make_test_content("process.env.SECRET; expect(add(1, 2)).toBe(3);")
                    )
                ]
            ),
        ),
        DIFF,
    )

    assert any("forbidden code" in error for error in result.errors)
    assert sandbox.calls == []


async def test_budget_stops_writing_and_review_but_keeps_verified_work(
    tmp_path: Path, settings: Settings
) -> None:
    write(tmp_path, "src/ops.ts", OPS)
    sandbox = FakeSandbox()
    llm = budgeted(max_calls=1)

    result = await run_agent_pipeline(dependencies(tmp_path, settings, sandbox, llm=llm), OPS_DIFF)

    assert result.verified_count == 1
    assert result.cost["calls"] == 1
    assert sum("call cap reached" in error for error in result.errors) >= 1
    assert [call["phase"] for call in sandbox.calls] == ["install", "test"]


async def test_generation_is_limited_to_max_tests(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/ops.ts", OPS)
    sandbox = FakeSandbox()

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            config=RepoConfig(max_tests=2),
        ),
        OPS_DIFF,
    )

    assert result.verified_count == 2
    assert result.errors == ["limited test generation to 2 of 3 gaps"]
    assert result.cost["calls"] == 3


async def test_review_llm_error_is_recorded(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox()

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            llm=budgeted([proposal_json(), raising]),
        ),
        DIFF,
    )

    assert result.verified_count == 1
    assert result.review is None
    assert any("review failed: provider down" in error for error in result.errors)


async def test_fixer_budget_exceeded_is_recorded(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox([failing_outcome(), failing_outcome()])
    llm = budgeted(max_calls=1)

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            llm=llm,
            config=RepoConfig(max_fix_attempts=1),
        ),
        DIFF,
    )

    assert result.attempts == 1
    assert result.rejected_count == 1
    assert result.cost["calls"] == 1
    assert any("call cap reached" in error for error in result.errors)
    assert [call["phase"] for call in sandbox.calls] == ["install", "test", "test"]


async def test_install_network_can_be_disabled_by_config(
    tmp_path: Path, settings: Settings
) -> None:
    write(tmp_path, "src/math.ts", MATH)
    sandbox = FakeSandbox()

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            config=RepoConfig(sandbox_install_network=False),
        ),
        DIFF,
    )

    assert result.verified_count == 1
    assert sandbox.calls[0]["phase"] == "install"
    assert sandbox.calls[0]["network_disabled"] is True


async def test_ui_functions_are_skipped_by_default(tmp_path: Path, settings: Settings) -> None:
    write(tmp_path, "src/button.tsx", BUTTON)
    sandbox = FakeSandbox()

    result = await run_agent_pipeline(dependencies(tmp_path, settings, sandbox), BUTTON_DIFF)

    assert result.verified == []
    assert sandbox.calls == []
    assert any("skipped 1 UI function" in error for error in result.errors)
    assert result.cost["calls"] == 1


async def test_ui_functions_get_jsdom_tests_when_enabled(
    tmp_path: Path, settings: Settings
) -> None:
    write(tmp_path, "src/button.tsx", BUTTON)
    sandbox = FakeSandbox()

    result = await run_agent_pipeline(
        dependencies(
            tmp_path,
            settings,
            sandbox,
            config=RepoConfig(include_ui_tests=True),
        ),
        BUTTON_DIFF,
    )

    assert result.verified_count == 1
    assert result.verified[0].file_path == "src/button.Button.test.tsx"
    content = (tmp_path / "src/button.Button.test.tsx").read_text(encoding="utf-8")
    assert content.startswith("// @vitest-environment jsdom")
    assert [call["phase"] for call in sandbox.calls] == ["install", "test"]


def test_dedupe_keeps_the_first_proposal_per_path() -> None:
    first = Proposal("a.test.ts", "a", "a.ts", "one")
    duplicate = Proposal("a.test.ts", "a", "a.ts", "two")
    other = Proposal("b.test.ts", "b", "b.ts", "three")

    assert _dedupe([first, duplicate, other]) == [first, other]


def test_add_error_caps_count_and_truncates_messages() -> None:
    state: dict[str, Any] = {"errors": [f"error {index}" for index in range(25)]}
    assert _add_error(state, "new") == [f"error {index}" for index in range(25)]

    state = {"errors": []}
    assert _add_error(state, "x" * 3000) == ["x" * 2000]


def test_load_coverage_returns_none_for_missing_or_invalid_files(tmp_path: Path) -> None:
    assert _load_coverage(tmp_path / "missing.json", tmp_path) is None

    invalid = tmp_path / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")
    assert _load_coverage(invalid, tmp_path) is None

    not_an_object = tmp_path / "array.json"
    not_an_object.write_text("[]", encoding="utf-8")
    assert _load_coverage(not_an_object, tmp_path) is None
