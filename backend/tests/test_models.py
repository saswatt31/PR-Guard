from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.db import Database
from app.models import (
    AgentStep,
    CodeReview,
    Delivery,
    GeneratedTest,
    Job,
    Run,
    RunStatus,
    SandboxExecution,
    TestStatus,
    new_id,
    utcnow,
)


def make_delivery(delivery_id: str = "delivery-1") -> Delivery:
    return Delivery(
        delivery_id=delivery_id,
        event="pull_request",
        action="opened",
        payload_sha256="a" * 64,
    )


def make_run(delivery_id: str = "delivery-1") -> Run:
    return Run(
        delivery_id=delivery_id,
        repo_full_name="acme/demo",
        repo_owner="acme",
        repo_name="demo",
        pr_number=7,
        head_sha="head123",
        base_sha="base123",
        installation_id=99,
        sender_login="octocat",
        status=RunStatus.QUEUED,
        config={"max_attempts": 3},
    )


def test_utcnow_is_timezone_aware() -> None:
    now = utcnow()
    assert now.tzinfo == UTC
    assert isinstance(now, datetime)


def test_new_id_is_unique() -> None:
    assert new_id() != new_id()


def test_create_all_creates_every_table(database: Database) -> None:
    tables = set(inspect(database.engine).get_table_names())
    assert tables == {
        "deliveries",
        "runs",
        "jobs",
        "agent_steps",
        "generated_tests",
        "sandbox_executions",
        "code_reviews",
    }


def test_full_run_graph_persists_and_loads(database: Database) -> None:
    with database.session() as session:
        delivery = make_delivery()
        run = make_run()
        delivery.runs.append(run)
        run.job = Job()
        run.steps.append(
            AgentStep(sequence=1, node="analyze_diff", summary="parsed 2 files", detail={"n": 2})
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
                coverage={"lines": 81.2},
            )
        )
        run.review = CodeReview(content="No blocking issues.")
        session.add(delivery)
        session.flush()
        run_id = run.id

    with database.session() as session:
        loaded = session.scalars(select(Run).where(Run.id == run_id)).one()
        assert loaded.repo_full_name == "acme/demo"
        assert loaded.job is not None
        assert loaded.steps[0].node == "analyze_diff"
        assert loaded.tests[0].status == "verified"
        assert loaded.sandbox_runs[0].coverage == {"lines": 81.2}
        assert loaded.review is not None
        assert loaded.config == {"max_attempts": 3}


def test_delivery_id_must_be_unique(database: Database) -> None:
    with database.session() as session:
        session.add(make_delivery())
    try:
        with database.session() as session:
            session.add(make_delivery())
    except IntegrityError:
        pass
    else:  # pragma: no cover - failure path is explicit
        raise AssertionError("duplicate delivery was accepted")


def test_run_repo_and_head_sha_must_be_unique(database: Database) -> None:
    with database.session() as session:
        first = make_delivery("unique-commit-1")
        first.runs.append(make_run("unique-commit-1"))
        session.add(first)

    with pytest.raises(IntegrityError), database.session() as session:
        second = make_delivery("unique-commit-2")
        second.runs.append(make_run("unique-commit-2"))
        session.add(second)


def test_deleting_run_cascades_children(database: Database) -> None:
    with database.session() as session:
        delivery = make_delivery()
        run = make_run()
        run.steps.append(AgentStep(sequence=1, node="analyze_diff"))
        run.job = Job()
        delivery.runs.append(run)
        session.add(delivery)
        session.flush()
        run_id = run.id

    with database.session() as session:
        run = session.get(Run, run_id)
        assert run is not None
        session.delete(run)

    with database.session() as session:
        assert session.scalars(select(AgentStep)).all() == []
        assert session.scalars(select(Job)).all() == []
        assert session.scalars(select(Delivery)).all() != []
