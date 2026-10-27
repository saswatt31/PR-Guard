"""Processor tests: fake GitHub, fake sandbox, FakeLLM, but real worker/DB/graph."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db import Database
from app.github.client import PostedComment
from app.github.errors import GitHubAPIError
from app.models import (
    AgentStep,
    CodeReview,
    GeneratedTest,
    Job,
    Run,
    RunStatus,
    SandboxExecution,
    TestStatus,
)
from app.queue.worker import Worker
from app.run_processor import RunProcessor
from app.sandbox.models import SandboxResult, SandboxStatus
from app.settings import Settings
from tests.test_models import make_delivery, make_run

MATH = """\
export function add(a: number, b: number) {
  return a + b;
}
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

README_DIFF = """\
diff --git a/README.md b/README.md
new file mode 100644
--- /dev/null
+++ b/README.md
@@ -0,0 +1 @@
+# Demo
"""


def make_tarball(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in files.items():
            data = content.encode("utf-8")
            member = tarfile.TarInfo(f"acme-demo-abc123/{name}")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


def coverage_payload(*, hits: int, line_pct: float) -> dict[str, Any]:
    return {
        "src/math.ts": {
            "fnMap": {
                "0": {
                    "name": "add",
                    "decl": {"start": {"line": 1}, "end": {"line": 3}},
                }
            },
            "f": {"0": hits},
        },
        "total": {"lines": {"pct": line_pct}},
    }


def write_json(root: Path, path: str, value: object) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value), encoding="utf-8")


def sandbox_result(
    phase: str,
    status: SandboxStatus | str = SandboxStatus.PASSED,
    *,
    stderr: str = "",
) -> SandboxResult:
    value = str(status)
    return SandboxResult(
        phase=phase,
        command=("fake",),
        status=value,
        exit_code=0 if value == "passed" else 1,
        timed_out=value == "timeout",
        duration_ms=2,
        stdout="",
        stderr=stderr,
        network_disabled=phase == "test",
        isolation="fake",
        error=None,
    )


def baseline_outcome(root: Path, _command: list[str] | None = None) -> SandboxResult:
    write_json(
        root,
        "coverage/coverage-final.json",
        coverage_payload(hits=0, line_pct=50.0),
    )
    return sandbox_result("test", SandboxStatus.FAILED, stderr="baseline has no test files")


def agent_passing_outcome(root: Path, _command: list[str] | None = None) -> SandboxResult:
    write_json(
        root,
        "vitest-results.json",
        {
            "testResults": [
                {
                    "name": "src/math.add.test.ts",
                    "status": "passed",
                    "assertionResults": [{"title": "executes", "status": "passed"}],
                }
            ]
        },
    )
    write_json(
        root,
        "coverage/coverage-final.json",
        coverage_payload(hits=1, line_pct=60.0),
    )
    return sandbox_result("test")


class FakeSandbox:
    def __init__(self, outcomes: list[Any] | None = None, *, default: Any = None) -> None:
        self.outcomes = list(outcomes or [])
        self.default = default or (lambda root, command: sandbox_result("test"))
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
        outcome = self.outcomes.pop(0) if self.outcomes else self.default
        return outcome(root, command) if callable(outcome) else outcome


class FakeGitHub:
    def __init__(
        self,
        diff: str,
        tarball: bytes,
        *,
        fail_download: bool = False,
        fail_comment: bool = False,
    ) -> None:
        self.diff = diff
        self.tarball = tarball
        self.fail_download = fail_download
        self.fail_comment = fail_comment
        self.comments: list[dict[str, Any]] = []
        self.closed = False

    async def get_pull_request_diff(
        self, installation_id: int, owner: str, repo: str, pr_number: int
    ) -> str:
        assert (installation_id, owner, repo, pr_number) == (99, "acme", "demo", 7)
        return self.diff

    async def download_tarball(
        self, installation_id: int, owner: str, repo: str, ref: str
    ) -> bytes:
        assert (installation_id, owner, repo) == (99, "acme", "demo")
        assert ref == "head123"
        if self.fail_download:
            raise GitHubAPIError(502, "download failed")
        return self.tarball

    async def post_comment(
        self,
        installation_id: int,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
    ) -> PostedComment:
        if self.fail_comment:
            raise GitHubAPIError(403, "comment forbidden")
        self.comments.append(
            {
                "installation_id": installation_id,
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "body": body,
            }
        )
        return PostedComment(
            id=123,
            html_url="https://github.test/acme/demo/pull/7#issuecomment-123",
        )

    async def aclose(self) -> None:
        self.closed = True


def enqueue(database: Database, *, delivery_id: str = "prguard-test-delivery") -> str:
    with database.session() as session:
        delivery = make_delivery(delivery_id)
        run = make_run(delivery_id)
        run.job = Job()
        delivery.runs.append(run)
        session.add(delivery)
        session.flush()
        return run.id


def load(database: Database, run_id: str) -> Run:
    with database.session() as session:
        run = session.get(Run, run_id)
        assert run is not None
        return run


def processor(
    database: Database,
    settings: Settings,
    workspace_root: Path,
    *,
    github: FakeGitHub,
    sandbox: FakeSandbox,
) -> RunProcessor:
    return RunProcessor(
        database,
        settings,
        github=github,
        sandbox=sandbox,
        workspace_root=workspace_root,
    )


async def test_processor_verifies_test_persists_rows_and_posts_one_comment(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    run_id = enqueue(database)
    github = FakeGitHub(DIFF, make_tarball({"src/math.ts": MATH}))
    sandbox = FakeSandbox(
        [
            lambda root, command: sandbox_result("install"),
            baseline_outcome,
            agent_passing_outcome,
        ]
    )
    workspaces = tmp_path / "workspaces"
    worker = Worker(
        database,
        processor(database, settings, workspaces, github=github, sandbox=sandbox),
        settings,
    )

    assert await worker.process_once() is True

    run = load(database, run_id)
    assert run.status == RunStatus.SUCCEEDED
    assert run.files_changed == 1
    assert run.functions_found == 1
    assert run.tests_generated == 1
    assert run.tests_verified == 1
    assert run.coverage_before == 50.0
    assert run.coverage_after == 60.0
    assert run.coverage_delta == 10.0
    assert run.llm_calls == 2
    assert run.comment_id == 123
    assert "1 verified" in (run.summary or "")
    assert run.config["run_baseline_coverage"] is True
    assert list(workspaces.iterdir()) == []

    with database.session() as session:
        tests = session.scalars(select(GeneratedTest)).all()
        assert len(tests) == 1
        assert tests[0].status == TestStatus.VERIFIED
        assert tests[0].file_path == "src/math.add.test.ts"
        assert "expect(result).toBe(result);" in tests[0].content
        steps = session.scalars(select(AgentStep).order_by(AgentStep.sequence)).all()
        assert [step.node for step in steps] == [
            "baseline",
            "analyze",
            "find_gaps",
            "write",
            "execute",
            "review",
        ]
        assert steps[0].status == "failed"
        assert steps[-1].status == "succeeded"
        sandbox_runs = session.scalars(select(SandboxExecution)).all()
        assert len(sandbox_runs) == 1
        assert sandbox_runs[0].phase == "test"
        review = session.scalars(select(CodeReview)).one()
        assert "FakeLLM review" in review.content

    assert [call["phase"] for call in sandbox.calls] == ["install", "test", "test"]
    assert sandbox.calls[0]["labels"] == {"run_id": run_id}
    assert len(github.comments) == 1
    body = github.comments[0]["body"]
    assert f"<!-- prguard:run:{run_id} -->" in body
    assert "50.00% → 60.00% (+10.00 pp)" in body
    assert "src/math.add.test.ts" in body
    assert "expect(result).toBe(result);" in body


async def test_baseline_without_coverage_falls_back_to_reference_heuristic(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    run_id = enqueue(database, delivery_id="baseline-no-coverage")
    github = FakeGitHub(DIFF, make_tarball({"src/math.ts": MATH}))
    sandbox = FakeSandbox(
        [
            lambda root, command: sandbox_result("install"),
            lambda root, command: sandbox_result("test"),
            agent_passing_outcome,
        ]
    )
    worker = Worker(
        database,
        processor(database, settings, tmp_path / "ws", github=github, sandbox=sandbox),
        settings,
    )

    await worker.process_once()

    run = load(database, run_id)
    assert run.status == RunStatus.SUCCEEDED
    assert run.coverage_before is None
    assert run.coverage_after == 60.0
    assert run.coverage_delta is None
    assert "baseline not measured" in (run.summary or "")
    with database.session() as session:
        baseline = session.scalars(select(AgentStep).where(AgentStep.node == "baseline")).one()
        assert baseline.status == "succeeded"
        assert "no coverage report" in baseline.summary


async def test_baseline_can_be_disabled_for_a_run_with_functions(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    run_id = enqueue(database, delivery_id="baseline-disabled")
    config = "run_baseline_coverage: false\n"
    github = FakeGitHub(
        DIFF,
        make_tarball({"src/math.ts": MATH, ".prguard.yml": config}),
    )
    sandbox = FakeSandbox(
        [
            lambda root, command: sandbox_result("install"),
            agent_passing_outcome,
        ]
    )
    worker = Worker(
        database,
        processor(database, settings, tmp_path / "ws", github=github, sandbox=sandbox),
        settings,
    )

    await worker.process_once()

    run = load(database, run_id)
    assert run.status == RunStatus.SUCCEEDED
    assert run.coverage_before is None
    assert run.coverage_after == 60.0
    assert [call["phase"] for call in sandbox.calls] == ["install", "test"]
    with database.session() as session:
        baseline = session.scalars(select(AgentStep).where(AgentStep.node == "baseline")).one()
        assert baseline.status == "skipped"


async def test_processor_skips_baseline_and_reports_no_gaps(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    run_id = enqueue(database, delivery_id="no-gaps")
    config = "run_baseline_coverage: false\nreview_code: false\n"
    github = FakeGitHub(
        README_DIFF,
        make_tarball({"README.md": "# Demo\n", ".prguard.yml": config}),
    )
    sandbox = FakeSandbox()
    worker = Worker(
        database,
        processor(database, settings, tmp_path / "ws", github=github, sandbox=sandbox),
        settings,
    )

    await worker.process_once()

    run = load(database, run_id)
    assert run.status == RunStatus.SUCCEEDED
    assert run.tests_generated == 0
    assert run.tests_verified == 0
    assert run.coverage_before is None
    assert run.coverage_after is None
    assert run.llm_calls == 0
    assert run.config["run_baseline_coverage"] is False
    assert run.config["review_code"] is False
    assert sandbox.calls == []
    assert len(github.comments) == 1
    body = github.comments[0]["body"]
    assert "0 verified tests" in body
    assert "No untested changed functions were found." in body

    with database.session() as session:
        steps = session.scalars(select(AgentStep).order_by(AgentStep.sequence)).all()
        assert [step.node for step in steps] == ["baseline", "analyze", "find_gaps", "review"]
        assert steps[0].status == "skipped"
        assert steps[-1].status == "skipped"
        assert session.scalars(select(GeneratedTest)).all() == []


async def test_processor_respects_post_comment_false(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    enqueue(database, delivery_id="no-comment")
    config = "post_comment: false\nrun_baseline_coverage: false\nreview_code: false\n"
    github = FakeGitHub(
        README_DIFF,
        make_tarball({"README.md": "# Demo\n", ".prguard.yml": config}),
    )
    worker = Worker(
        database,
        processor(database, settings, tmp_path / "ws", github=github, sandbox=FakeSandbox()),
        settings,
    )

    await worker.process_once()

    assert github.comments == []


async def test_invalid_repo_config_fails_run_without_sandbox_or_comment(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    run_id = enqueue(database, delivery_id="bad-config")
    github = FakeGitHub(
        DIFF,
        make_tarball({"src/math.ts": MATH, ".prguard.yml": "max_tests: 999\n"}),
    )
    sandbox = FakeSandbox()
    worker = Worker(
        database,
        processor(database, settings, tmp_path / "ws", github=github, sandbox=sandbox),
        settings,
    )

    await worker.process_once()

    run = load(database, run_id)
    assert run.status == RunStatus.FAILED
    assert "max_tests" in (run.error or "")
    assert sandbox.calls == []
    assert github.comments == []


async def test_github_download_failure_marks_run_failed(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    run_id = enqueue(database, delivery_id="bad-download")
    github = FakeGitHub(DIFF, b"", fail_download=True)
    worker = Worker(
        database,
        processor(
            database,
            settings,
            tmp_path / "ws",
            github=github,
            sandbox=FakeSandbox(),
        ),
        settings,
    )

    await worker.process_once()

    run = load(database, run_id)
    assert run.status == RunStatus.FAILED
    assert "GitHub API 502" in (run.error or "")
    assert github.comments == []


async def test_comment_failure_keeps_persisted_results_and_fails_run(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    run_id = enqueue(database, delivery_id="comment-failure")
    github = FakeGitHub(
        DIFF,
        make_tarball({"src/math.ts": MATH}),
        fail_comment=True,
    )
    sandbox = FakeSandbox(
        [
            lambda root, command: sandbox_result("install"),
            baseline_outcome,
            agent_passing_outcome,
        ]
    )
    worker = Worker(
        database,
        processor(database, settings, tmp_path / "ws", github=github, sandbox=sandbox),
        settings,
    )

    await worker.process_once()

    run = load(database, run_id)
    assert run.status == RunStatus.FAILED
    assert "GitHub API 403" in (run.error or "")
    assert run.tests_verified == 1
    assert run.comment_id is None
    with database.session() as session:
        assert len(session.scalars(select(GeneratedTest)).all()) == 1


async def test_baseline_install_failure_rejects_drafts_but_reports(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    run_id = enqueue(database, delivery_id="baseline-install-fail")
    github = FakeGitHub(DIFF, make_tarball({"src/math.ts": MATH}))
    failed_install = sandbox_result("install", SandboxStatus.FAILED, stderr="npm ERR! offline")
    sandbox = FakeSandbox([failed_install, failed_install])
    worker = Worker(
        database,
        processor(database, settings, tmp_path / "ws", github=github, sandbox=sandbox),
        settings,
    )

    await worker.process_once()

    run = load(database, run_id)
    assert run.status == RunStatus.SUCCEEDED
    assert run.tests_generated == 1
    assert run.tests_verified == 0
    assert [call["phase"] for call in sandbox.calls] == ["install", "install"]
    assert len(github.comments) == 1
    assert "dependency install failed" in github.comments[0]["body"]
    with database.session() as session:
        test = session.scalars(select(GeneratedTest)).one()
        assert test.status == TestStatus.REJECTED
        assert "npm ERR! offline" in (test.last_error or "")


async def test_existing_comment_id_suppresses_a_retry_comment(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    run_id = enqueue(database, delivery_id="already-commented")
    with database.session() as session:
        session.get(Run, run_id).comment_id = 999
    github = FakeGitHub(
        README_DIFF,
        make_tarball({"README.md": "# Demo\n", ".prguard.yml": "review_code: false\n"}),
    )
    worker = Worker(
        database,
        processor(database, settings, tmp_path / "ws", github=github, sandbox=FakeSandbox()),
        settings,
    )

    await worker.process_once()

    assert github.comments == []
    assert load(database, run_id).comment_id == 999


async def test_new_processor_can_retry_without_duplicating_rows(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    run_id = enqueue(database, delivery_id="retry-run")
    run = load(database, run_id)
    run.status = RunStatus.RUNNING
    first = RunProcessor(
        database,
        settings,
        github=FakeGitHub(DIFF, make_tarball({"src/math.ts": MATH})),
        sandbox=FakeSandbox(
            [
                lambda root, command: sandbox_result("install"),
                baseline_outcome,
                agent_passing_outcome,
            ]
        ),
        workspace_root=tmp_path / "ws",
    )
    await first.process(run_id)

    second = RunProcessor(
        database,
        settings,
        github=FakeGitHub(DIFF, make_tarball({"src/math.ts": MATH})),
        sandbox=FakeSandbox(
            [
                lambda root, command: sandbox_result("install"),
                baseline_outcome,
                agent_passing_outcome,
            ]
        ),
        workspace_root=tmp_path / "ws",
    )
    await second.process(run_id)

    with database.session() as session:
        assert len(session.scalars(select(GeneratedTest)).all()) == 1
        assert len(session.scalars(select(AgentStep)).all()) == 6
        assert len(session.scalars(select(SandboxExecution)).all()) == 1
        assert len(session.scalars(select(CodeReview)).all()) == 1
