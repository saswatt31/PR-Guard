"""Export genuine local PR-Guard runs into the dashboard's static demo data.

The default path runs the real local smoke pipeline (``backend/scripts/demo_smoke.py``)
and then serialises the resulting SQLite rows through the same Pydantic response
models the FastAPI dashboard uses. The output is therefore shaped exactly like
``GET /api/runs``, ``GET /api/runs/{id}`` and ``GET /api/stats``.

This is a capture tool, not a fake-data generator. It refuses to write files if a
secret-like token is found in the serialised output. The manifest records exactly
which parts of the system were real and which were fakes.

Usage (from the repository root):

    .venv/Scripts/python.exe scripts/capture_demo_data.py
    .venv/Scripts/python.exe scripts/capture_demo_data.py --no-smoke
    .venv/Scripts/python.exe scripts/capture_demo_data.py --out dashboard/public/demo-data
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.db import Database  # noqa: E402
from app.models import Run  # noqa: E402
from app.schemas import (  # noqa: E402
    DemoInfo,
    RunDetail,
    RunList,
    RunStats,
    RunSummary,
)

DEFAULT_DATABASE = ROOT / "data" / "demo.db"
DEFAULT_OUTPUT = ROOT / "dashboard" / "public" / "demo-data"
DEMO_REPO = "acme/prguard-demo"
DEMO_PR = 1
REPO_URL = "https://github.com/saswatt31/PR-Guard"
RECORDING_URL = f"{REPO_URL}/blob/main/docs/DEMO_RECORDING.md"

SENSITIVE_KEY = re.compile(
    r"^(?:.*_)?(?:api_?key|access_token|refresh_token|auth_token|github_token|"
    r"token|secret|password|passwd|private_key)$",
    re.I,
)
SECRET_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"gh[pousr]_[A-Za-z0-9_]{20,}",
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"sk-[A-Za-z0-9]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"AIza[0-9A-Za-z\-_]{35}",
        r"xox[baprs]-[A-Za-z0-9-]{10,}",
        r"glpat-[A-Za-z0-9_-]{20,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]{16,}",
    )
]
WINDOWS_PATH = re.compile(r"[A-Za-z]:\\[^\s\"'<>]+")
POSIX_PRIVATE_PATH = re.compile(r"/(?:tmp|home|Users)/[^\s\"'<>]+")


def run_demo_smoke(database: Path) -> None:
    """Run the real local pipeline and let its assertions fail the capture."""

    command = [sys.executable, str(BACKEND / "scripts" / "demo_smoke.py"), "--database", str(database)]
    print(f"running: {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=BACKEND, check=True)


def git_metadata() -> tuple[str, str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # Ignore untracked files and the generated capture itself: those files are the
    # output being produced. A dirty flag means tracked source did not match the
    # commit. This lets a capture be regenerated from a committed tree without
    # claiming the source was dirty just because the JSON was rewritten.
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    generated_prefix = "dashboard/public/demo-data/"
    dirty_lines = []
    for line in status.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if not path.startswith(generated_prefix):
            dirty_lines.append(line)
    return commit, branch, bool(dirty_lines)


def clean_text(value: str) -> str:
    value = WINDOWS_PATH.sub("<local-path>", value)
    value = POSIX_PRIVATE_PATH.sub("<local-path>", value)
    return value


def clean_value(value: Any, key: str = "") -> Any:
    """Recursively redact secret-named keys and local absolute paths."""

    if SENSITIVE_KEY.search(key):
        return "<redacted>"
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        return [clean_value(item, key) for item in value]
    if isinstance(value, dict):
        return {str(k): clean_value(v, str(k)) for k, v in value.items()}
    return value


def normalise_timestamps(value: Any) -> Any:
    """SQLite drops tzinfo; mark known UTC timestamps explicitly for the browser."""

    if isinstance(value, dict):
        return {
            key: (
                f"{item}Z"
                if key.endswith("_at")
                and isinstance(item, str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?", item)
                else normalise_timestamps(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalise_timestamps(item) for item in value]
    return value


def sanitise_detail(detail: RunDetail, allowed_repos: set[str]) -> RunDetail:
    """Remove identifying fields while keeping every measured number intact."""

    data = detail.model_dump(mode="json")
    repo = data["repo_full_name"]
    if repo not in allowed_repos:
        data["repo_full_name"] = "demo/private-repo"
        data["head_sha"] = "d" * 40
        data["base_sha"] = "b" * 40
    data["installation_id"] = 0
    data["sender_login"] = "demo"
    data["delivery_id"] = "demo-delivery"
    # The local fake GitHub accepts a comment but no real comment URL exists.
    data["comment_id"] = None
    data["comment_url"] = None
    data["config"] = clean_value(data.get("config") or {})
    data["error"] = clean_text(data["error"]) if data.get("error") else None
    data["steps"] = [
        {
            **step,
            "summary": clean_text(step.get("summary") or ""),
            "detail": clean_value(step.get("detail") or {}),
            "error": clean_text(step["error"]) if step.get("error") else None,
        }
        for step in data["steps"]
    ]
    data["tests"] = [
        {
            **test,
            "content": clean_text(test.get("content") or ""),
            "last_error": clean_text(test["last_error"]) if test.get("last_error") else None,
        }
        for test in data["tests"]
    ]
    data["sandbox_runs"] = [
        {
            **sandbox,
            "stdout": clean_text(sandbox.get("stdout") or ""),
            "stderr": clean_text(sandbox.get("stderr") or ""),
            "coverage": clean_value(sandbox.get("coverage") or {}),
        }
        for sandbox in data["sandbox_runs"]
    ]
    if data.get("review"):
        data["review"]["content"] = clean_text(data["review"].get("content") or "")
    data["summary"] = clean_text(data["summary"]) if data.get("summary") else None
    return RunDetail.model_validate(normalise_timestamps(data))


def load_runs(database_path: Path) -> tuple[list[RunDetail], RunStats, DemoInfo]:
    if not database_path.exists():
        raise SystemExit(f"database not found: {database_path}\nRun without --no-smoke first.")

    database = Database(f"sqlite:///{database_path.as_posix()}")
    try:
        with database.session() as session:
            runs = session.scalars(
                select(Run)
                .order_by(Run.created_at.desc(), Run.id.desc())
                .options(
                    selectinload(Run.steps),
                    selectinload(Run.tests),
                    selectinload(Run.sandbox_runs),
                    selectinload(Run.review),
                )
            ).all()
            if not runs:
                raise SystemExit(f"no runs in {database_path}")

            grouped = dict(
                session.execute(select(Run.status, func.count()).group_by(Run.status)).all()
            )
            tests = session.execute(
                select(func.sum(Run.tests_generated), func.sum(Run.tests_verified))
            ).one()
            cost = session.scalar(select(func.sum(Run.cost_usd))) or 0.0
            coverage = session.scalar(select(func.avg(Run.coverage_delta)))
            duration = session.scalar(select(func.avg(Run.duration_ms)))

            details = [RunDetail.model_validate(run) for run in runs]
            stats = RunStats(
                total_runs=sum(int(value) for value in grouped.values()),
                queued=int(grouped.get("queued", 0)),
                running=int(grouped.get("running", 0)),
                succeeded=int(grouped.get("succeeded", 0)),
                failed=int(grouped.get("failed", 0)),
                skipped=int(grouped.get("skipped", 0)),
                tests_generated=int(tests[0] or 0),
                tests_verified=int(tests[1] or 0),
                total_cost_usd=round(float(cost), 6),
                avg_coverage_delta=(round(float(coverage), 2) if coverage is not None else None),
                avg_duration_ms=(int(duration) if duration is not None else None),
            )
            demo = DemoInfo(enabled=True, run_count=len(details))
    finally:
        database.dispose()

    allowed = {DEMO_REPO}
    return [sanitise_detail(detail, allowed) for detail in details], stats, demo


def assert_no_secrets(payload: str, path: Path) -> None:
    for pattern in SECRET_PATTERNS:
        match = pattern.search(payload)
        if match:
            raise SystemExit(
                f"refusing to write {path}: secret-like value matched "
                f"{pattern.pattern!r} ({match.group(0)[:12]}…)"
            )


def write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    assert_no_secrets(payload, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)} ({len(payload):,} bytes)")


def build_manifest(details: list[RunDetail]) -> dict[str, Any]:
    commit, branch, dirty = git_metadata()
    return {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "git_commit_short": commit[:7],
        "git_branch": branch,
        "git_dirty": dirty,
        "source": "backend/scripts/demo_smoke.py (real worker, npm and Vitest)",
        "repository": DEMO_REPO,
        "pull_request": DEMO_PR,
        "provider": "FakeLLM (deterministic; zero provider calls)",
        "github": "in-process fake (no GitHub App, token, webhook or real comment)",
        "sandbox": "LocalSandboxRunner (no container, no network isolation, not a boundary)",
        "run_config": {
            "sandbox_mode": "local",
            "llm_provider": "fake",
            "max_llm_calls": 8,
            "max_total_tokens": 50000,
            "max_cost_usd": 0.25,
            "sandbox_install_timeout_seconds": 300,
            "sandbox_timeout_seconds": 180,
        },
        "run_count": len(details),
        "run_ids": [detail.id for detail in details],
        "repo_url": REPO_URL,
        "recording_url": RECORDING_URL,
        "caveats": [
            "The pipeline, npm install, Vitest execution and SQLite persistence are real.",
            "The sandbox is LocalSandboxRunner, not Docker; it is not a security boundary.",
            "GitHub is an in-process fake; no GitHub App, installation token or real PR comment exists.",
            "The LLM is FakeLLM with scripted output; no Groq or Anthropic request was made.",
            "Comment URLs and installation identifiers were removed during export.",
            "Cost is $0.00 because FakeLLM does not bill tokens.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--no-smoke",
        action="store_true",
        help="Export an existing database instead of running the local pipeline first.",
    )
    args = parser.parse_args(argv)

    database_path = args.database.resolve()
    output = args.out.resolve()
    if not args.no_smoke:
        run_demo_smoke(database_path)

    details, stats, demo = load_runs(database_path)
    manifest = build_manifest(details)
    summaries = [
        RunSummary.model_validate(detail.model_dump(mode="json")) for detail in details
    ]
    run_list = RunList(items=summaries, total=len(summaries), limit=len(summaries), offset=0)

    # Start from a clean directory so a deleted run cannot linger in the bundle.
    output.mkdir(parents=True, exist_ok=True)
    for stale in output.glob("runs/*.json"):
        stale.unlink()
    for stale in output.glob("*.json"):
        stale.unlink()

    write_json(output / "manifest.json", manifest)
    write_json(output / "stats.json", stats.model_dump(mode="json"))
    write_json(output / "runs.json", run_list.model_dump(mode="json"))
    write_json(output / "demo.json", demo.model_dump(mode="json"))
    write_json(output / "details.json", [detail.model_dump(mode="json") for detail in details])
    for detail in details:
        write_json(output / "runs" / f"{detail.id}.json", detail.model_dump(mode="json"))

    print(
        f"captured {len(details)} run(s), {stats.tests_verified}/{stats.tests_generated} "
        f"verified test(s), commit {manifest['git_commit_short']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
