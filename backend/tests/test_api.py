"""Read-only dashboard API tests against a real SQLite database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.db import Database
from app.models import (
    AgentStep,
    CodeReview,
    GeneratedTest,
    Run,
    RunStatus,
    SandboxExecution,
    TestStatus,
)
from tests.test_models import make_delivery, make_run


def add_run(
    database: Database,
    delivery_id: str,
    *,
    status: RunStatus = RunStatus.SUCCEEDED,
    repo: str = "acme/demo",
    created_at: datetime | None = None,
    **values: Any,
) -> str:
    owner, name = repo.split("/", 1)
    with database.session() as session:
        delivery = make_delivery(delivery_id)
        run = make_run(delivery_id)
        run.status = status
        run.repo_full_name = repo
        run.repo_owner = owner
        run.repo_name = name
        # Each fixture run represents a distinct commit; runs are unique by repo+head.
        run.head_sha = f"head-{delivery_id}"
        if created_at is not None:
            run.created_at = created_at
            run.updated_at = created_at
        for key, value in values.items():
            setattr(run, key, value)
        delivery.runs.append(run)
        session.add(delivery)
        session.flush()
        return run.id


def test_list_runs_is_newest_first_and_paginates(database: Database, client: TestClient) -> None:
    now = datetime.now(UTC)
    oldest = add_run(database, "old", created_at=now - timedelta(minutes=2))
    newest = add_run(database, "new", created_at=now)
    middle = add_run(database, "middle", created_at=now - timedelta(minutes=1))

    response = client.get("/api/runs", params={"limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [newest, middle]

    page = client.get("/api/runs", params={"limit": 2, "offset": 2}).json()
    assert [item["id"] for item in page["items"]] == [oldest]


def test_list_runs_filters_status_and_repository(database: Database, client: TestClient) -> None:
    add_run(database, "ok", repo="acme/demo")
    add_run(database, "bad", status=RunStatus.FAILED, repo="acme/other")
    add_run(database, "bad-demo", status=RunStatus.FAILED, repo="acme/demo-extra")

    failed = client.get("/api/runs", params={"status": "failed"}).json()
    assert failed["total"] == 2
    assert {item["id"] for item in failed["items"]} == {
        item["id"] for item in client.get("/api/runs").json()["items"] if item["status"] == "failed"
    }

    demo = client.get("/api/runs", params={"repo": "demo", "status": "failed"}).json()
    assert demo["total"] == 1
    assert demo["items"][0]["repo_full_name"] == "acme/demo-extra"

    case_diff = client.get("/api/runs", params={"repo": "DEMO"}).json()
    assert case_diff["total"] == 2


def test_list_runs_rejects_invalid_pagination_and_status(client: TestClient) -> None:
    assert client.get("/api/runs", params={"limit": 0}).status_code == 422
    assert client.get("/api/runs", params={"limit": 101}).status_code == 422
    assert client.get("/api/runs", params={"offset": -1}).status_code == 422
    assert client.get("/api/runs", params={"status": "unknown"}).status_code == 422


def test_get_run_returns_all_children(database: Database, client: TestClient) -> None:
    run_id = add_run(database, "detail")
    with database.session() as session:
        run = session.get(Run, run_id)
        assert run is not None
        run.summary = "1 verified"
        run.config = {"max_tests": 4}
        run.comment_id = 123
        run.comment_url = "https://github.test/comment/123"
        run.steps.append(
            AgentStep(
                sequence=1,
                node="analyze",
                status="succeeded",
                summary="parsed",
                detail={"functions": 1},
                duration_ms=12,
            )
        )
        run.tests.append(
            GeneratedTest(
                file_path="src/math.test.ts",
                function_name="add",
                source_file="src/math.ts",
                content="it('adds', () => {})",
                status=TestStatus.VERIFIED,
                attempts=1,
            )
        )
        run.sandbox_runs.append(
            SandboxExecution(
                phase="test",
                image="prguard-sandbox:node20",
                command=["npx", "vitest", "run"],
                status="passed",
                exit_code=0,
                timed_out=False,
                stdout="ok",
                stderr="",
                network_disabled=True,
                coverage={"line_pct": 80.0, "files": 1},
            )
        )
        run.review = CodeReview(content="No blocking issues.")

    response = client.get(f"/api/runs/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == run_id
    assert body["config"] == {"max_tests": 4}
    assert body["comment_url"] == "https://github.test/comment/123"
    assert body["steps"][0]["node"] == "analyze"
    assert body["tests"][0]["status"] == "verified"
    assert body["sandbox_runs"][0]["command"] == ["npx", "vitest", "run"]
    assert body["review"]["content"] == "No blocking issues."


def test_get_run_404(client: TestClient) -> None:
    response = client.get("/api/runs/does-not-exist")

    assert response.status_code == 404
    assert response.json()["detail"] == "run not found"


def test_stats_aggregate_runs_and_tests(database: Database, client: TestClient) -> None:
    add_run(
        database,
        "one",
        tests_generated=3,
        tests_verified=2,
        cost_usd=0.2,
        coverage_delta=10.0,
        duration_ms=100,
    )
    add_run(
        database,
        "two",
        status=RunStatus.FAILED,
        tests_generated=1,
        tests_verified=0,
        cost_usd=0.1,
        coverage_delta=-5.0,
        duration_ms=300,
    )
    add_run(database, "three", status=RunStatus.QUEUED)

    response = client.get("/api/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["total_runs"] == 3
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert body["queued"] == 1
    assert body["running"] == 0
    assert body["skipped"] == 0
    assert body["tests_generated"] == 4
    assert body["tests_verified"] == 2
    assert body["total_cost_usd"] == 0.3
    assert body["avg_coverage_delta"] == 2.5
    assert body["avg_duration_ms"] == 200


def test_stats_are_zero_for_an_empty_database(client: TestClient) -> None:
    response = client.get("/api/stats")

    assert response.status_code == 200
    assert response.json() == {
        "total_runs": 0,
        "queued": 0,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "tests_generated": 0,
        "tests_verified": 0,
        "total_cost_usd": 0.0,
        "avg_coverage_delta": None,
        "avg_duration_ms": None,
    }


def test_demo_info_reports_disabled_and_count(client: TestClient, database: Database) -> None:
    add_run(database, "demo-count")

    response = client.get("/api/demo")

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "run_count": 1}
