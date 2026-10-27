from sqlalchemy import select

from app.db import Database, build_engine
from app.models import AgentStep, Delivery, GeneratedTest, Job, Run, SandboxExecution
from app.schemas import (
    CodeReviewOut,
    GeneratedTestOut,
    RunDetail,
    RunSummary,
    SandboxExecutionOut,
    StepOut,
)
from tests.test_models import make_delivery, make_run


def test_rollback_on_exception(database: Database) -> None:
    try:
        with database.session() as session:
            session.add(make_delivery("rollback-me"))
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with database.session() as session:
        assert session.scalars(select(Delivery)).all() == []


def test_in_memory_engine_supported() -> None:
    engine = build_engine("sqlite:///:memory:")
    assert engine.url.database == ":memory:"
    engine.dispose()


def build_detail(database: Database):
    with database.session() as session:
        delivery = make_delivery()
        run = make_run()
        run.files_changed = 2
        run.functions_found = 3
        run.tests_generated = 2
        run.tests_verified = 1
        run.llm_calls = 4
        run.input_tokens = 100
        run.output_tokens = 50
        run.cost_usd = 0.01
        run.summary = "done"
        run.coverage_before = 60.0
        run.coverage_after = 71.0
        run.coverage_delta = 11.0
        run.duration_ms = 1234
        run.comment_url = "https://github.com/acme/demo/pull/7#issuecomment-1"
        run.comment_id = 1
        run.job = Job()
        run.steps.append(
            AgentStep(
                sequence=1,
                node="analyze_diff",
                summary="parsed",
                detail={"files": 2},
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.001,
                duration_ms=20,
            )
        )
        run.tests.append(
            GeneratedTest(
                file_path="src/math.test.ts",
                function_name="add",
                source_file="src/math.ts",
                content="test",
                attempts=1,
            )
        )
        run.sandbox_runs.append(
            SandboxExecution(
                phase="test",
                image="img",
                command=["npx", "vitest", "run"],
                status="passed",
                exit_code=0,
                duration_ms=100,
                stdout="ok",
                stderr="",
                coverage={"lines": 71.0},
            )
        )
        from app.models import CodeReview

        run.review = CodeReview(content="looks fine", cost_usd=0.002)
        delivery.runs.append(run)
        session.add(delivery)
        session.flush()
        run_id = run.id

    with database.session() as session:
        loaded = session.scalars(select(Run).where(Run.id == run_id)).one()
        detail = RunDetail.model_validate(loaded)
        summary = RunSummary.model_validate(loaded)
        step = StepOut.model_validate(loaded.steps[0])
        test = GeneratedTestOut.model_validate(loaded.tests[0])
        sandbox = SandboxExecutionOut.model_validate(loaded.sandbox_runs[0])
        review = CodeReviewOut.model_validate(loaded.review)
        return detail, summary, step, test, sandbox, review


def test_response_schemas_serialize_orm_graph(database: Database) -> None:
    detail, summary, step, test, sandbox, review = build_detail(database)

    assert detail.repo_full_name == "acme/demo"
    assert detail.steps[0].node == "analyze_diff"
    assert detail.tests[0].function_name == "add"
    assert detail.sandbox_runs[0].network_disabled is True
    assert detail.review is not None
    assert summary.tests_verified == 1
    assert step.detail == {"files": 2}
    assert test.status == "proposed"
    assert sandbox.coverage == {"lines": 71.0}
    assert review.content == "looks fine"
    assert detail.model_dump()["coverage_delta"] == 11.0
