"""LangGraph pipeline: diff -> gaps -> writer -> sandbox -> fixer -> review."""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.models import PipelineResult, RejectedTest, TestProposal
from app.agents.parsing import (
    ProposalParseError,
    first_proposal_for,
    parse_proposals,
)
from app.agents.prompts import build_fix_prompt, build_review_prompt, build_test_prompt
from app.agents.results import parse_vitest_results_file
from app.agents.safety import (
    UnsafeTestError,
    suggest_test_path,
    unique_test_path,
    validate_proposal,
    write_test_proposal,
)
from app.config.repo import RepoConfig
from app.coverage.gap import GapDecision, find_gaps
from app.coverage.istanbul import CoverageReport, load_coverage_file
from app.diff.analyzer import analyze_diff
from app.diff.models import DiffAnalysis, FunctionInfo
from app.llm.base import BudgetExceeded, LLMError
from app.llm.budget import BudgetedLLM
from app.sandbox.models import SandboxResult
from app.settings import Settings

MAX_ERRORS = 25


class AgentState(TypedDict, total=False):
    diff_text: str
    analysis: DiffAnalysis
    gaps: list[GapDecision]
    drafts: list[TestProposal]
    failed: list[TestProposal]
    verified: list[TestProposal]
    rejected: list[RejectedTest]
    attempts: int
    installed: bool
    sandbox_results: list[dict[str, Any]]
    coverage_after: CoverageReport | None
    review: str | None
    errors: list[str]
    steps: list[dict[str, Any]]


@dataclass
class AgentDependencies:
    settings: Settings
    config: RepoConfig
    llm: BudgetedLLM
    sandbox: Any
    repo_root: Path
    coverage_before: CoverageReport | None = None
    run_id: str = ""
    initial_analysis: DiffAnalysis | None = None
    dependencies_installed: bool = False


def build_agent_graph(deps: AgentDependencies):
    builder = StateGraph(AgentState)
    builder.add_node("analyze", partial(_analyze_node, deps))
    builder.add_node("find_gaps", partial(_gaps_node, deps))
    builder.add_node("write", partial(_write_node, deps))
    builder.add_node("execute", partial(_execute_node, deps))
    builder.add_node("fix", partial(_fix_node, deps))
    builder.add_node("review", partial(_review_node, deps))
    builder.add_edge(START, "analyze")
    builder.add_edge("analyze", "find_gaps")
    builder.add_conditional_edges(
        "find_gaps",
        _route_after_gaps,
        {"write": "write", "review": "review"},
    )
    builder.add_edge("write", "execute")
    builder.add_conditional_edges(
        "execute",
        partial(_route_after_execute, deps),
        {"fix": "fix", "review": "review"},
    )
    builder.add_edge("fix", "execute")
    builder.add_edge("review", END)
    return builder.compile()


async def run_agent_pipeline(deps: AgentDependencies, diff_text: str) -> PipelineResult:
    graph = build_agent_graph(deps)
    initial: AgentState = {
        "diff_text": diff_text,
        "attempts": 0,
        "installed": deps.dependencies_installed,
        "sandbox_results": [],
        "errors": [],
        "drafts": [],
        "failed": [],
        "verified": [],
        "rejected": [],
        "steps": [],
    }
    final = await graph.ainvoke(initial)
    failed = list(final.get("failed") or [])
    rejected = list(final.get("rejected") or [])
    known = {item.proposal.file_path for item in rejected}
    for draft in failed:
        if draft.file_path not in known:
            rejected.append(
                RejectedTest(
                    draft,
                    draft.last_error or "test did not pass before the attempt cap",
                )
            )
            known.add(draft.file_path)
    analysis = final.get("analysis")
    if analysis is None:  # pragma: no cover - analyze always runs
        analysis = DiffAnalysis()
    coverage_after = final.get("coverage_after")
    before_pct = deps.coverage_before.line_pct if deps.coverage_before else None
    after_pct = coverage_after.line_pct if coverage_after else None
    delta = (
        round(after_pct - before_pct, 2)
        if before_pct is not None and after_pct is not None
        else None
    )
    return PipelineResult(
        analysis=analysis,
        verified=_dedupe(final.get("verified") or []),
        rejected=rejected,
        gaps=list(final.get("gaps") or []),
        errors=list(final.get("errors") or []),
        review=final.get("review"),
        coverage_before=deps.coverage_before,
        coverage_after=coverage_after,
        coverage_delta=delta,
        cost=deps.llm.summary.to_dict(),
        sandbox_results=list(final.get("sandbox_results") or []),
        steps=list(final.get("steps") or []),
        attempts=int(final.get("attempts") or 0),
    )


def _dedupe(proposals: list[TestProposal]) -> list[TestProposal]:
    seen: set[str] = set()
    result: list[TestProposal] = []
    for proposal in proposals:
        if proposal.file_path not in seen:
            result.append(proposal)
            seen.add(proposal.file_path)
    return result


def _add_error(state: AgentState, message: str) -> list[str]:
    errors = list(state.get("errors") or [])
    if len(errors) < MAX_ERRORS:
        errors.append(message[:2000])
    return errors


def _step(
    node: str,
    started: float,
    *,
    status: str = "succeeded",
    summary: str = "",
    **detail: Any,
) -> dict[str, Any]:
    return {
        "node": node,
        "status": status,
        "summary": summary[:2000],
        "detail": detail,
        "duration_ms": max(0, int((time.perf_counter() - started) * 1000)),
    }


def _with_step(state: AgentState, step: dict[str, Any]) -> list[dict[str, Any]]:
    return [*(state.get("steps") or []), step]


def _analyze_node(deps: AgentDependencies, state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    analysis = deps.initial_analysis or analyze_diff(state.get("diff_text", ""), deps.repo_root)
    return {
        "analysis": analysis,
        "steps": _with_step(
            state,
            _step(
                "analyze",
                started,
                summary=(
                    f"parsed {analysis.changed_file_count} changed file(s), "
                    f"{len(analysis.functions)} function(s)"
                ),
                files=analysis.changed_file_count,
                functions=len(analysis.functions),
                errors=analysis.errors[:10],
            ),
        ),
    }


def _gaps_node(deps: AgentDependencies, state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    analysis = state["analysis"]
    result = find_gaps(
        analysis.functions,
        deps.repo_root,
        coverage=deps.coverage_before,
        enabled_paths=list(deps.config.enabled_paths),
    )
    gaps = result.gaps
    ui_gaps = [gap for gap in gaps if gap.function.is_ui and not deps.config.include_ui_tests]
    if ui_gaps:
        gaps = [gap for gap in gaps if deps.config.include_ui_tests or not gap.function.is_ui]
    gaps = sorted(
        gaps,
        key=lambda gap: (
            not gap.function.is_new,
            gap.function.file_path,
            gap.function.start_line,
        ),
    )
    errors = list(state.get("errors") or [])
    if ui_gaps:
        errors.append(
            f"skipped {len(ui_gaps)} UI function(s); set include_ui_tests: true "
            "to generate jsdom tests"
        )
    unlimited = len(gaps)
    if len(gaps) > deps.config.max_tests:
        errors.append(f"limited test generation to {deps.config.max_tests} of {len(gaps)} gaps")
        gaps = gaps[: deps.config.max_tests]
    return {
        "gaps": gaps,
        "errors": errors,
        "steps": _with_step(
            state,
            _step(
                "find_gaps",
                started,
                summary=(
                    f"{len(gaps)} gap(s), {len(result.covered)} covered, "
                    f"{len(result.skipped)} skipped"
                ),
                gaps=len(gaps),
                gaps_before_limit=unlimited,
                covered=len(result.covered),
                skipped=len(result.skipped),
                ui_skipped=len(ui_gaps),
            ),
        ),
    }


async def _write_node(deps: AgentDependencies, state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    drafts = list(state.get("drafts") or [])
    initial_drafts = len(drafts)
    errors = list(state.get("errors") or [])
    for gap in state.get("gaps") or []:
        function = gap.function
        if len(drafts) >= deps.config.max_tests:
            break
        test_path = unique_test_path(
            deps.repo_root, suggest_test_path(function.file_path, function.name)
        )
        prompt = build_test_prompt(
            function,
            test_path=test_path,
            existing_tests=gap.existing_tests,
            reason=gap.reason,
        )
        try:
            response = await deps.llm.complete(prompt, max_tokens=1800, json_mode=True)
        except BudgetExceeded as exc:
            errors.append(str(exc))
            break
        except LLMError as exc:
            errors.append(f"writer failed for {function.qualified_name}: {exc}")
            continue
        try:
            proposals = parse_proposals(response.text)
            proposal = first_proposal_for(
                proposals,
                function_name=function.name,
                source_file=function.file_path,
            )
            if proposal.framework != "vitest":
                raise UnsafeTestError("only Vitest proposals are executable in this run")
            proposal = validate_proposal(
                deps.repo_root,
                proposal,
                expected_function=function.name,
                expected_source=function.file_path,
            )
            if (deps.repo_root / proposal.file_path).exists():
                raise UnsafeTestError(
                    f"proposal would overwrite an existing test: {proposal.file_path}"
                )
            write_test_proposal(deps.repo_root, proposal)
            drafts.append(proposal)
        except (ProposalParseError, UnsafeTestError, OSError) as exc:
            errors.append(f"writer output rejected for {function.qualified_name}: {exc}")
    wrote = len(drafts) - initial_drafts
    gaps = len(state.get("gaps") or [])
    return {
        "drafts": drafts,
        "errors": errors,
        "steps": _with_step(
            state,
            _step(
                "write",
                started,
                status="failed" if gaps and wrote == 0 else "succeeded",
                summary=f"wrote {wrote}/{gaps} draft(s)",
                drafts=wrote,
                gaps=gaps,
                errors=max(0, len(errors) - (len(state.get("errors") or []))),
            ),
        ),
    }


async def _execute_node(deps: AgentDependencies, state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    drafts = list(state.get("drafts") or [])
    errors = list(state.get("errors") or [])
    sandbox_results = list(state.get("sandbox_results") or [])
    if not drafts:
        return {
            "failed": [],
            "verified": [],
            "errors": errors,
            "steps": _with_step(
                state,
                _step("execute", started, status="skipped", summary="no drafts to execute"),
            ),
        }

    installed = bool(state.get("installed"))
    install: SandboxResult | None = None
    if not installed:
        install = await _run_sandbox(
            deps,
            list(deps.config.install_command),
            phase="install",
            network_disabled=not deps.config.sandbox_install_network,
            timeout_seconds=deps.settings.sandbox_install_timeout_seconds,
        )
        sandbox_results.append(install.to_dict())
        if not install.passed:
            reason = install.error or install.stderr or install.stdout or "install failed"
            return {
                "installed": False,
                "failed": [],
                "verified": [],
                "rejected": [
                    RejectedTest(draft, f"dependency install failed: {reason}") for draft in drafts
                ],
                "sandbox_results": sandbox_results,
                "errors": _add_error(state, f"sandbox install failed: {reason}"),
                "steps": _with_step(
                    state,
                    _step(
                        "execute",
                        started,
                        status="failed",
                        summary=f"install failed; {len(drafts)} draft(s) rejected",
                        install=install.status,
                        drafts=len(drafts),
                        verified=0,
                        failed=len(drafts),
                    ),
                ),
            }
        installed = True

    _clear_outputs(deps.repo_root, deps.config.results_file, deps.config.coverage_file)
    test_result = await _run_sandbox(
        deps,
        list(deps.config.test_command),
        phase="test",
        network_disabled=True,
        timeout_seconds=deps.settings.sandbox_timeout_seconds,
    )
    sandbox_results.append(test_result.to_dict())
    if test_result.status in {"timeout", "error"}:
        errors.append(test_result.error or f"sandbox test phase {test_result.status}")

    results_path = deps.repo_root / deps.config.results_file
    coverage_path = deps.repo_root / deps.config.coverage_file
    known_paths = {draft.file_path for draft in drafts}
    report = parse_vitest_results_file(results_path, known_paths)
    report_exists = results_path.is_file()
    coverage_after = _load_coverage(coverage_path, deps.repo_root)

    verified: list[TestProposal] = []
    failed: list[TestProposal] = []
    for draft in drafts:
        file_result = report.get(draft.file_path)
        if file_result is not None:
            passed = file_result.passed
            failure = file_result.failure
        elif report_exists:
            passed = False
            failure = "test file was missing from the Vitest report"
        else:
            passed = test_result.passed
            failure = (
                ""
                if passed
                else (
                    test_result.stderr or test_result.stdout or test_result.error or "test failed"
                )
            )
        if passed and coverage_after is not None:
            function = _find_function(state["analysis"].functions, draft)
            if function is not None:
                hits = coverage_after.function_hits(
                    function.file_path,
                    function.name,
                    function.start_line,
                    function.end_line,
                )
                if hits is not None and hits <= 0:
                    passed = False
                    failure = "test passed but coverage shows 0 executions of the target function"
        if passed:
            verified.append(draft)
        else:
            draft.last_error = (failure or "test failed")[:4000]
            failed.append(draft)
    if test_result.status == "timeout":
        errors.append(f"test phase timed out after {deps.settings.sandbox_timeout_seconds}s")
    return {
        "installed": installed,
        "verified": verified,
        "failed": failed,
        "coverage_after": coverage_after,
        "sandbox_results": sandbox_results,
        "errors": errors,
        "steps": _with_step(
            state,
            _step(
                "execute",
                started,
                status=("failed" if test_result.status in {"timeout", "error"} else "succeeded"),
                summary=f"verified {len(verified)}, rejected {len(failed)}",
                install="reused" if install is None else install.status,
                test=test_result.status,
                drafts=len(drafts),
                verified=len(verified),
                failed=len(failed),
                report_exists=report_exists,
                coverage_pct=coverage_after.line_pct if coverage_after else None,
                round=int(state.get("attempts") or 0) + 1,
            ),
        ),
    }


def _route_after_gaps(state: AgentState) -> str:
    return "write" if state.get("gaps") else "review"


def _route_after_execute(deps: AgentDependencies, state: AgentState) -> str:
    failed = state.get("failed") or []
    attempts = int(state.get("attempts") or 0)
    return "fix" if failed and attempts < deps.config.max_fix_attempts else "review"


async def _fix_node(deps: AgentDependencies, state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    failed = list(state.get("failed") or [])
    if not failed:
        return {
            "steps": _with_step(
                state,
                _step("fix", started, status="skipped", summary="no failed drafts"),
            )
        }
    analysis = state["analysis"]
    drafts = list(state.get("drafts") or [])
    by_path = {draft.file_path: draft for draft in drafts}
    errors = list(state.get("errors") or [])
    for draft in failed:
        function = _find_function(analysis.functions, draft)
        if function is None:
            errors.append(f"fixer could not locate {draft.source_file}::{draft.function_name}")
            continue
        prompt = build_fix_prompt(
            draft,
            function=function,
            failure=draft.last_error or "unknown test failure",
            test_path=draft.file_path,
        )
        try:
            response = await deps.llm.complete(prompt, max_tokens=1800, json_mode=True)
            proposals = parse_proposals(response.text)
            proposal = first_proposal_for(
                proposals,
                function_name=draft.function_name,
                source_file=draft.source_file,
            )
            proposal = validate_proposal(
                deps.repo_root,
                proposal,
                expected_function=draft.function_name,
                expected_source=draft.source_file,
            )
            if proposal.file_path != draft.file_path:
                proposal.file_path = draft.file_path
            proposal.attempts = draft.attempts + 1
            proposal.last_error = None
            write_test_proposal(deps.repo_root, proposal)
            by_path[draft.file_path] = proposal
        except BudgetExceeded as exc:
            errors.append(str(exc))
            break
        except (LLMError, ProposalParseError, UnsafeTestError, OSError) as exc:
            draft.last_error = f"fixer output rejected: {exc}"[:4000]
    updated = [by_path[draft.file_path] for draft in drafts]
    rewritten = sum(1 for draft in failed if by_path.get(draft.file_path) is not draft)
    return {
        "drafts": updated,
        "failed": [],
        "attempts": int(state.get("attempts") or 0) + 1,
        "errors": errors,
        "steps": _with_step(
            state,
            _step(
                "fix",
                started,
                status="succeeded" if rewritten else "failed",
                summary=f"rewrote {rewritten}/{len(failed)} failed draft(s)",
                rewritten=rewritten,
                failed=len(failed),
                round=int(state.get("attempts") or 0) + 1,
            ),
        ),
    }


async def _review_node(deps: AgentDependencies, state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    if not deps.config.review_code:
        return {
            "review": None,
            "steps": _with_step(
                state,
                _step("review", started, status="skipped", summary="review disabled"),
            ),
        }
    verified = list(state.get("verified") or [])
    failed = list(state.get("failed") or [])
    prompt = build_review_prompt(
        diff=state.get("diff_text", ""),
        verified=verified,
        rejected=failed,
    )
    try:
        response = await deps.llm.complete(prompt, max_tokens=600)
    except BudgetExceeded as exc:
        return {
            "review": None,
            "errors": _add_error(state, str(exc)),
            "steps": _with_step(
                state,
                _step("review", started, status="failed", summary="review budget exceeded"),
            ),
        }
    except LLMError as exc:
        return {
            "review": None,
            "errors": _add_error(state, f"review failed: {exc}"),
            "steps": _with_step(
                state,
                _step("review", started, status="failed", summary="review LLM error"),
            ),
        }
    return {
        "review": response.text.strip()[:8000],
        "steps": _with_step(
            state,
            _step("review", started, summary="review completed", chars=len(response.text)),
        ),
    }


async def _run_sandbox(
    deps: AgentDependencies,
    command: list[str],
    *,
    phase: str,
    network_disabled: bool,
    timeout_seconds: int,
) -> SandboxResult:
    return await asyncio.to_thread(
        partial(
            deps.sandbox.run,
            deps.repo_root,
            command,
            phase=phase,
            network_disabled=network_disabled,
            timeout_seconds=timeout_seconds,
            labels={"run_id": deps.run_id} if deps.run_id else None,
        )
    )


def _load_coverage(path: Path, root: Path) -> CoverageReport | None:
    if not path.is_file():
        return None
    try:
        return load_coverage_file(path, repo_root=root)
    except (OSError, ValueError):
        return None


def _clear_outputs(root: Path, *relative_paths: str) -> None:
    for relative in relative_paths:
        target = root / relative
        with contextlib.suppress(OSError):
            if target.is_file():
                target.unlink()


def _find_function(functions: list[FunctionInfo], draft: TestProposal) -> FunctionInfo | None:
    for function in functions:
        if function.file_path == draft.source_file and function.name == draft.function_name:
            return function
    return None
