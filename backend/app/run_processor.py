"""Orchestrate one queued run: download, checkout, baseline, agent, persist, comment.

The worker owns the job lifecycle. This module owns the PR-specific work and is
deliberately injectable so tests can use a fake GitHub client, sandbox and LLM without
network, Docker or an installation token.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from sqlalchemy import delete

from app.agents.graph import AgentDependencies, run_agent_pipeline
from app.agents.models import PipelineResult, RejectedTest, TestProposal
from app.comment import format_pr_comment
from app.config.repo import RepoConfig, load_repo_config
from app.coverage.istanbul import CoverageReport, load_coverage_file
from app.db import Database
from app.diff.analyzer import analyze_diff
from app.diff.models import DiffAnalysis
from app.github.client import GitHubClient
from app.github.repo import safe_extract_tarball
from app.llm.budget import BudgetedLLM
from app.llm.factory import build_budgeted_llm
from app.models import (
    AgentStep,
    CodeReview,
    GeneratedTest,
    Run,
    SandboxExecution,
    TestStatus,
)
from app.sandbox.factory import SandboxRunner, build_sandbox
from app.sandbox.models import SandboxResult
from app.settings import Settings

PipelineRunner = Callable[[AgentDependencies, str], Awaitable[PipelineResult]]
LLMFactory = Callable[[Settings, RepoConfig], BudgetedLLM]


@dataclass(frozen=True)
class RunContext:
    id: str
    repo_owner: str
    repo_name: str
    repo_full_name: str
    pr_number: int
    head_sha: str
    installation_id: int


@dataclass
class BaselineOutcome:
    coverage: CoverageReport | None = None
    install: SandboxResult | None = None
    test: SandboxResult | None = None
    installed: bool = False
    status: str = "skipped"
    summary: str = ""
    duration_ms: int = 0

    def step(self) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "coverage_pct": self.coverage.line_pct if self.coverage else None,
            "installed": self.installed,
        }
        if self.install is not None:
            detail["install"] = self.install.status
        if self.test is not None:
            detail["test"] = self.test.status
            detail["exit_code"] = self.test.exit_code
        return {
            "node": "baseline",
            "status": self.status,
            "summary": self.summary[:2000],
            "detail": detail,
            "duration_ms": self.duration_ms,
        }


class RunProcessor:
    """Process one run id. The returned coroutine is accepted by ``Worker``."""

    def __init__(
        self,
        db: Database,
        settings: Settings,
        *,
        github: GitHubClient | None = None,
        sandbox: SandboxRunner | None = None,
        workspace_root: Path | None = None,
        llm_factory: LLMFactory = build_budgeted_llm,
        pipeline_runner: PipelineRunner = run_agent_pipeline,
    ) -> None:
        self.db = db
        self.settings = settings
        self._github = github
        self._sandbox = sandbox
        self.workspace_root = workspace_root
        self.llm_factory = llm_factory
        self.pipeline_runner = pipeline_runner

    async def __call__(self, run_id: str) -> None:
        await self.process(run_id)

    async def process(self, run_id: str) -> None:
        started = time.perf_counter()
        context = self._load_context(run_id)
        github = self._github or GitHubClient(self.settings)
        owns_github = self._github is None
        workspace: Path | None = None
        try:
            if self.workspace_root is not None:
                self.workspace_root.mkdir(parents=True, exist_ok=True)
            workspace = Path(
                tempfile.mkdtemp(
                    prefix=f"prguard-{run_id[:8]}-",
                    dir=str(self.workspace_root) if self.workspace_root else None,
                )
            )
            diff = await github.get_pull_request_diff(
                context.installation_id,
                context.repo_owner,
                context.repo_name,
                context.pr_number,
            )
            tarball = await github.download_tarball(
                context.installation_id,
                context.repo_owner,
                context.repo_name,
                context.head_sha,
            )
            safe_extract_tarball(tarball, workspace)
            config = load_repo_config(workspace)
            self._save_config(context.id, config)

            analysis = analyze_diff(diff, workspace)
            sandbox = self._sandbox or build_sandbox(self.settings)
            baseline = await self._baseline(
                context,
                workspace,
                config,
                analysis,
                sandbox,
            )
            llm = self.llm_factory(self.settings, config)
            deps = AgentDependencies(
                settings=self.settings,
                config=config,
                llm=llm,
                sandbox=sandbox,
                repo_root=workspace,
                coverage_before=baseline.coverage,
                run_id=context.id,
                initial_analysis=analysis,
                dependencies_installed=baseline.installed,
            )
            result = await self.pipeline_runner(deps, diff)
            duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            self._persist(
                context,
                config,
                result,
                baseline,
                duration_ms=duration_ms,
            )
            if config.post_comment:
                await self._post_comment(context, result, github)
        finally:
            if workspace is not None:
                shutil.rmtree(workspace, ignore_errors=True)
            if owns_github:
                await github.aclose()

    def _load_context(self, run_id: str) -> RunContext:
        with self.db.session() as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError(f"run {run_id} does not exist")
            return RunContext(
                id=run.id,
                repo_owner=run.repo_owner,
                repo_name=run.repo_name,
                repo_full_name=run.repo_full_name,
                pr_number=run.pr_number,
                head_sha=run.head_sha,
                installation_id=run.installation_id,
            )

    def _save_config(self, run_id: str, config: RepoConfig) -> None:
        with self.db.session() as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError(f"run {run_id} does not exist")
            run.config = config.to_public_dict()

    async def _baseline(
        self,
        context: RunContext,
        workspace: Path,
        config: RepoConfig,
        analysis: DiffAnalysis,
        sandbox: SandboxRunner,
    ) -> BaselineOutcome:
        started = time.perf_counter()
        if not config.run_baseline_coverage:
            return BaselineOutcome(
                status="skipped",
                summary="baseline coverage disabled by .prguard.yml",
            )
        if not analysis.functions:
            return BaselineOutcome(
                status="skipped",
                summary="no changed functions; baseline coverage not needed",
            )

        install = await self._run_sandbox(
            sandbox,
            workspace,
            list(config.install_command),
            phase="install",
            network_disabled=not config.sandbox_install_network,
            timeout_seconds=self.settings.sandbox_install_timeout_seconds,
            run_id=context.id,
        )
        if not install.passed:
            reason = install.error or install.stderr or install.stdout or "install failed"
            return BaselineOutcome(
                install=install,
                status="failed",
                summary=f"baseline install failed: {reason}",
                duration_ms=_elapsed_ms(started),
            )

        _clear_outputs(workspace, config.results_file, config.coverage_file)
        test = await self._run_sandbox(
            sandbox,
            workspace,
            list(config.test_command),
            phase="test",
            network_disabled=True,
            timeout_seconds=self.settings.sandbox_timeout_seconds,
            run_id=context.id,
        )
        coverage = _try_load_coverage(workspace / config.coverage_file, workspace)
        if coverage is None:
            summary = f"baseline tests {test.status}; no coverage report at {config.coverage_file}"
        else:
            summary = (
                f"baseline tests {test.status}; coverage {coverage.line_pct:.2f}%"
                if coverage.line_pct is not None
                else f"baseline tests {test.status}; coverage report loaded"
            )
        return BaselineOutcome(
            coverage=coverage,
            install=install,
            test=test,
            installed=True,
            status="succeeded" if test.passed else "failed",
            summary=summary,
            duration_ms=_elapsed_ms(started),
        )

    async def _run_sandbox(
        self,
        sandbox: SandboxRunner,
        workspace: Path,
        command: list[str],
        *,
        phase: str,
        network_disabled: bool,
        timeout_seconds: int,
        run_id: str,
    ) -> SandboxResult:
        return await asyncio.to_thread(
            partial(
                sandbox.run,
                workspace,
                command,
                phase=phase,
                network_disabled=network_disabled,
                timeout_seconds=timeout_seconds,
                labels={"run_id": run_id} if run_id else None,
            )
        )

    def _persist(
        self,
        context: RunContext,
        config: RepoConfig,
        result: PipelineResult,
        baseline: BaselineOutcome,
        *,
        duration_ms: int,
    ) -> None:
        cost = result.cost
        before = baseline.coverage.line_pct if baseline.coverage else None
        after = result.coverage_after.line_pct if result.coverage_after else None
        summary = _build_summary(result)
        steps = [baseline.step(), *result.steps]
        rejected = result.rejected
        generated = _dedupe_tests(result.verified, rejected)

        with self.db.session() as session:
            run = session.get(Run, context.id)
            if run is None:
                raise ValueError(f"run {context.id} does not exist")
            run.config = config.to_public_dict()
            run.files_changed = result.analysis.changed_file_count
            run.functions_found = len(result.analysis.functions)
            run.tests_generated = len(generated)
            run.tests_verified = len(result.verified)
            run.llm_calls = int(cost.get("calls", 0))
            run.input_tokens = int(cost.get("input_tokens", 0))
            run.output_tokens = int(cost.get("output_tokens", 0))
            run.cost_usd = float(cost.get("cost_usd", 0.0))
            run.coverage_before = before
            run.coverage_after = after
            run.coverage_delta = result.coverage_delta
            run.summary = summary
            run.duration_ms = duration_ms

            session.execute(delete(AgentStep).where(AgentStep.run_id == context.id))
            session.execute(delete(GeneratedTest).where(GeneratedTest.run_id == context.id))
            session.execute(delete(SandboxExecution).where(SandboxExecution.run_id == context.id))
            session.execute(delete(CodeReview).where(CodeReview.run_id == context.id))

            for sequence, step in enumerate(steps, start=1):
                detail_value = step.get("detail")
                detail = detail_value if isinstance(detail_value, dict) else {}
                session.add(
                    AgentStep(
                        run_id=context.id,
                        sequence=sequence,
                        node=str(step.get("node", "unknown"))[:64],
                        status=str(step.get("status", "succeeded"))[:20],
                        attempt=int(step.get("attempt", detail.get("round", 1)) or 1),
                        summary=str(step.get("summary", ""))[:2000],
                        detail=detail,
                        duration_ms=max(0, int(step.get("duration_ms", 0) or 0)),
                    )
                )

            for proposal in result.verified:
                session.add(
                    GeneratedTest(
                        run_id=context.id,
                        file_path=proposal.file_path,
                        function_name=proposal.function_name,
                        source_file=proposal.source_file,
                        framework=proposal.framework,
                        content=proposal.content,
                        status=TestStatus.VERIFIED,
                        attempts=proposal.attempts,
                        last_error=None,
                    )
                )
            for item in rejected:
                proposal = item.proposal
                session.add(
                    GeneratedTest(
                        run_id=context.id,
                        file_path=proposal.file_path,
                        function_name=proposal.function_name,
                        source_file=proposal.source_file,
                        framework=proposal.framework,
                        content=proposal.content,
                        status=TestStatus.REJECTED,
                        attempts=proposal.attempts,
                        last_error=item.reason[:4000],
                    )
                )

            for sandbox_run in result.sandbox_results:
                phase = str(sandbox_run.get("phase", "test"))
                coverage = (
                    {"line_pct": after, "files": len(result.coverage_after.files)}
                    if phase == "test" and result.coverage_after is not None
                    else None
                )
                session.add(
                    SandboxExecution(
                        run_id=context.id,
                        phase=phase,
                        image=self.settings.sandbox_image,
                        command=[str(part) for part in sandbox_run.get("command") or []],
                        network_disabled=bool(sandbox_run.get("network_disabled", True)),
                        status=str(sandbox_run.get("status", "error")),
                        exit_code=_optional_int(sandbox_run.get("exit_code")),
                        timed_out=bool(sandbox_run.get("timed_out", False)),
                        duration_ms=max(0, int(sandbox_run.get("duration_ms", 0) or 0)),
                        stdout=str(sandbox_run.get("stdout", ""))[:120_000],
                        stderr=str(sandbox_run.get("stderr", ""))[:120_000],
                        coverage=coverage,
                    )
                )

            if result.review:
                session.add(
                    CodeReview(
                        run_id=context.id,
                        content=result.review[:20_000],
                        # Review cost is included in the run total; it is not billed twice.
                        cost_usd=0.0,
                    )
                )

    async def _post_comment(
        self,
        context: RunContext,
        result: PipelineResult,
        github: GitHubClient,
    ) -> None:
        with self.db.session() as session:
            run = session.get(Run, context.id)
            if run is None:
                raise ValueError(f"run {context.id} does not exist")
            if run.comment_id is not None:
                return
        body = format_pr_comment(context.id, result)
        posted = await github.post_comment(
            context.installation_id,
            context.repo_owner,
            context.repo_name,
            context.pr_number,
            body,
        )
        with self.db.session() as session:
            run = session.get(Run, context.id)
            if run is None:
                return
            run.comment_id = posted.id
            run.comment_url = posted.html_url[:500]


def _dedupe_tests(verified: list[TestProposal], rejected: list[RejectedTest]) -> list[str]:
    paths = {proposal.file_path for proposal in verified}
    paths.update(item.proposal.file_path for item in rejected)
    return sorted(paths)


def _build_summary(result: PipelineResult) -> str:
    analysis = result.analysis
    before = result.coverage_before.line_pct if result.coverage_before else None
    after = result.coverage_after.line_pct if result.coverage_after else None
    if before is not None and after is not None and result.coverage_delta is not None:
        coverage = f"coverage {before:.2f}% → {after:.2f}% ({result.coverage_delta:+.2f} pp)"
    elif after is not None:
        coverage = f"coverage {after:.2f}% (baseline not measured)"
    else:
        coverage = "coverage not measured"
    summary = (
        f"{len(result.verified)} verified, {len(result.rejected)} not verified; "
        f"{analysis.changed_file_count} changed file(s), {len(analysis.functions)} function(s), "
        f"{len(result.gaps)} gap(s); {coverage}"
    )
    if result.errors:
        summary += f"; {len(result.errors)} warning(s)"
    return summary[:4000]


def _try_load_coverage(path: Path, workspace: Path) -> CoverageReport | None:
    if not path.is_file():
        return None
    try:
        return load_coverage_file(path, repo_root=workspace)
    except (OSError, ValueError):
        return None


def _clear_outputs(root: Path, *relative_paths: str) -> None:
    for relative in relative_paths:
        target = root / relative
        try:
            if target.is_file():
                target.unlink()
        except OSError:
            continue


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
