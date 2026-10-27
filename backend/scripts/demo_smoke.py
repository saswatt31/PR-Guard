"""Run the real pipeline locally against the demo PR and record a dashboard run.

This is a development/demo tool, not a production path:

- the sandbox is ``LocalSandboxRunner`` (NOT a security boundary);
- GitHub is a deterministic fake (no App, no installation token, no network);
- the LLM is ``FakeLLM`` with one scripted proposal (no provider call).

It still executes real npm/Vitest inside a real workspace, so it proves the orchestration
and verification wiring on a machine without Docker. Do not describe the output as a
Docker-sandbox or live-LLM verification.

Usage (from ``backend/``):

    ..\\.venv\\Scripts\\python.exe scripts\\demo_smoke.py
    ..\\.venv\\Scripts\\python.exe scripts\\demo_smoke.py --database ..\\data\\demo.db
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Sequence
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db import Database  # noqa: E402
from app.github.client import PostedComment  # noqa: E402
from app.llm.base import Message  # noqa: E402
from app.llm.budget import BudgetedLLM  # noqa: E402
from app.llm.fake import FakeLLM  # noqa: E402
from app.models import (  # noqa: E402
    AgentStep,
    Delivery,
    GeneratedTest,
    Job,
    Run,
    RunStatus,
    SandboxExecution,
)
from app.queue.worker import Worker  # noqa: E402
from app.run_processor import RunProcessor  # noqa: E402
from app.sandbox.local import LocalSandboxRunner  # noqa: E402
from app.settings import Settings  # noqa: E402

DEMO_REPO = REPO_ROOT / "demo-repo"
PATCH = DEMO_REPO / "demo-pr.patch"
DEMO_TEST = """import { describe, expect, it } from "vitest";

import { normalizeScore } from "../src/score";

describe("normalizeScore", () => {
  it("returns a fraction inside the 0..1 range", () => {
    expect(normalizeScore(25, 100)).toBe(0.25);
  });

  it("clamps values below zero and above the maximum", () => {
    expect(normalizeScore(-5, 100)).toBe(0);
    expect(normalizeScore(150, 100)).toBe(1);
  });

  it("rejects invalid inputs", () => {
    expect(() => normalizeScore(Number.NaN, 100)).toThrow(RangeError);
    expect(() => normalizeScore(1, 0)).toThrow(RangeError);
  });
});
"""


class DemoGitHub:
    """The three GitHub calls the processor makes, served from local fixtures."""

    def __init__(self, diff: str, tarball: bytes) -> None:
        self.diff = diff
        self.tarball = tarball
        self.comment_body: str | None = None

    async def get_pull_request_diff(
        self, installation_id: int, owner: str, repo: str, pr_number: int
    ) -> str:
        del installation_id, owner, repo, pr_number
        return self.diff

    async def download_tarball(
        self, installation_id: int, owner: str, repo: str, ref: str
    ) -> bytes:
        del installation_id, owner, repo, ref
        return self.tarball

    async def post_comment(
        self, installation_id: int, owner: str, repo: str, pr_number: int, body: str
    ) -> PostedComment:
        del installation_id, owner, repo, pr_number
        self.comment_body = body
        return PostedComment(id=4242, html_url="http://localhost:3000/demo/comment/4242")

    async def aclose(self) -> None:
        return None


def _scripted_llm(messages: Sequence[Message]) -> str:
    prompt = "\n".join(message.get("content", "") for message in messages)
    if "<TASK>review</TASK>" in prompt:
        return "No blocking issues. The generated test covers the new function."
    return json.dumps(
        {
            "proposals": [
                {
                    "file_path": "tests/score.test.ts",
                    "function_name": "normalizeScore",
                    "source_file": "src/score.ts",
                    "content": DEMO_TEST,
                    "framework": "vitest",
                    "reasoning": "Scripted demo proposal for the local smoke run.",
                }
            ]
        }
    )


def build_tarball(staging: Path) -> bytes:
    """Package the patched demo repository with GitHub-like top-level stripping."""

    import io

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_dir():
                continue
            relative = path.relative_to(staging).as_posix()
            archive.add(path, arcname=f"acme-demo/{relative}", recursive=False)
    return buffer.getvalue()


def prepare_staging(root: Path) -> Path:
    staging = root / "checkout"
    shutil.copytree(
        DEMO_REPO,
        staging,
        ignore=shutil.ignore_patterns("node_modules", "coverage", "vitest-results.json", ".git"),
    )
    subprocess.run(
        ["git", "apply", str(PATCH)],
        cwd=staging,
        check=True,
        capture_output=True,
        text=True,
    )
    return staging


def create_run(database: Database) -> str:
    with database.session() as session:
        delivery = Delivery(
            delivery_id="demo-local-delivery",
            event="pull_request",
            action="opened",
            payload_sha256="0" * 64,
        )
        run = Run(
            delivery=delivery,
            repo_full_name="acme/prguard-demo",
            repo_owner="acme",
            repo_name="prguard-demo",
            pr_number=1,
            head_sha="d" * 40,
            base_sha="b" * 40,
            installation_id=99,
            sender_login="demo",
            is_fork=False,
            status=RunStatus.QUEUED,
        )
        session.add(run)
        session.flush()
        session.add(Job(run_id=run.id))
        return run.id


async def execute(args: argparse.Namespace) -> int:
    database_path = args.database.resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url=f"sqlite:///{database_path.as_posix()}",
        demo_mode=True,
        sandbox_mode="local",
        llm_provider="fake",
        max_llm_calls=8,
        max_total_tokens=50_000,
        max_cost_usd=0.25,
        sandbox_install_timeout_seconds=300,
        sandbox_timeout_seconds=180,
    )
    database = Database(settings.database_url)
    database.create_all()
    run_id = create_run(database)

    with tempfile.TemporaryDirectory(prefix="prguard-demo-") as temp:
        temp_path = Path(temp)
        staging = prepare_staging(temp_path)
        tarball = build_tarball(staging)
        diff = PATCH.read_text(encoding="utf-8")
        github = DemoGitHub(diff, tarball)

        def llm_factory(_settings: Settings, _config: object) -> BudgetedLLM:
            return BudgetedLLM(
                FakeLLM([_scripted_llm]),
                max_calls=8,
                max_total_tokens=50_000,
                max_cost_usd=0.25,
            )

        processor = RunProcessor(
            database,
            settings,
            github=github,
            sandbox=LocalSandboxRunner(settings),
            workspace_root=temp_path / "workspaces",
            llm_factory=llm_factory,
        )
        worker = Worker(database, processor, settings)
        processed = await worker.process_once()
        if not processed:
            raise RuntimeError("worker did not claim the demo job")

        with database.session() as session:
            run = session.get(Run, run_id)
            assert run is not None
            tests = session.scalars(
                select(GeneratedTest).where(GeneratedTest.run_id == run_id)
            ).all()
            steps = session.scalars(
                select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.sequence)
            ).all()
            sandboxes = session.scalars(
                select(SandboxExecution).where(SandboxExecution.run_id == run_id)
            ).all()

            print(f"run: {run.id}")
            print(f"status: {run.status}")
            print(f"summary: {run.summary}")
            print(f"coverage: {run.coverage_before} -> {run.coverage_after}")
            print(f"tests: {run.tests_verified} verified / {run.tests_generated} generated")
            comment_length = len(github.comment_body or "")
            print(f"comment: id={run.comment_id} url={run.comment_url} body={comment_length} chars")
            print("steps:")
            for step in steps:
                print(f"  {step.sequence}. {step.node} [{step.status}] {step.summary}")
            print("generated tests:")
            for test in tests:
                print(f"  {test.status}: {test.file_path} ({test.function_name})")
            print("sandbox executions:")
            for sandbox in sandboxes:
                print(
                    f"  {sandbox.phase}: {sandbox.status} exit={sandbox.exit_code} "
                    f"network_disabled={sandbox.network_disabled} {sandbox.duration_ms} ms"
                )

            if github.comment_body:
                comment_path = database_path.parent / "demo-comment.md"
                comment_path.write_text(github.comment_body, encoding="utf-8")
                print(f"comment body written to {comment_path}")

        if database_path.exists():
            print(f"database: {database_path}")
        return 0 if run is not None and run.status == RunStatus.SUCCEEDED else 1


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=REPO_ROOT / "data" / "demo.db",
        help="SQLite file to create (replaced if it exists)",
    )
    args = parser.parse_args(argv)
    return asyncio.run(execute(args))


if __name__ == "__main__":
    raise SystemExit(main())
