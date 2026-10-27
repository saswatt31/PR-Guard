import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.db import Database
from app.models import Job, JobStatus, Run, RunStatus, utcnow
from app.queue.worker import Worker, claim_next_job, reclaim_stale_jobs
from app.settings import Settings
from tests.test_models import make_delivery, make_run


def enqueue(database: Database, *, delivery_id: str = "d1", attempts: int = 0) -> str:
    with database.session() as session:
        delivery = make_delivery(delivery_id)
        run = make_run(delivery_id)
        run.job = Job(attempts=attempts)
        delivery.runs.append(run)
        session.add(delivery)
        session.flush()
        return run.id


def load(database: Database, run_id: str) -> Run:
    with database.session() as session:
        run = session.get(Run, run_id)
        assert run is not None
        return run


async def test_process_once_returns_false_when_no_jobs(
    database: Database, settings: Settings
) -> None:
    async def processor(_run_id: str) -> None:
        raise AssertionError("should not be called")

    worker = Worker(database, processor, settings)
    assert await worker.process_once() is False


async def test_successful_processor_marks_run_succeeded(
    database: Database, settings: Settings
) -> None:
    run_id = enqueue(database)
    seen: list[str] = []

    async def processor(claimed_run_id: str) -> None:
        seen.append(claimed_run_id)
        current = load(database, claimed_run_id)
        assert current.status == RunStatus.RUNNING

    worker = Worker(database, processor, settings)
    assert await worker.process_once() is True
    assert seen == [run_id]

    run = load(database, run_id)
    assert run.status == RunStatus.SUCCEEDED
    assert run.duration_ms is not None
    assert run.error is None
    with database.session() as session:
        job = session.scalars(select(Job)).one()
        assert job.status == JobStatus.DONE
        assert job.finished_at is not None


async def test_failing_processor_records_error(database: Database, settings: Settings) -> None:
    run_id = enqueue(database)

    async def processor(_run_id: str) -> None:
        raise RuntimeError("sandbox unavailable")

    worker = Worker(database, processor, settings)
    assert await worker.process_once() is True

    run = load(database, run_id)
    assert run.status == RunStatus.FAILED
    assert run.error == "RuntimeError: sandbox unavailable"
    with database.session() as session:
        job = session.scalars(select(Job)).one()
        assert job.status == JobStatus.FAILED
        assert "sandbox unavailable" in (job.last_error or "")


async def test_processor_that_marks_failed_is_not_overwritten(
    database: Database, settings: Settings
) -> None:
    run_id = enqueue(database)

    async def processor(claimed_run_id: str) -> None:
        with database.session() as session:
            run = session.get(Run, claimed_run_id)
            run.status = RunStatus.FAILED

    worker = Worker(database, processor, settings)
    await worker.process_once()
    assert load(database, run_id).status == RunStatus.FAILED


def test_claim_marks_run_running_and_increments_attempts(
    database: Database, settings: Settings
) -> None:
    run_id = enqueue(database)
    job = claim_next_job(database)
    assert job is not None
    assert job.attempts == 1
    assert load(database, run_id).status == RunStatus.RUNNING
    assert claim_next_job(database) is None


def test_reclaim_stale_job_under_cap(database: Database, settings: Settings) -> None:
    run_id = enqueue(database, attempts=1)
    with database.session() as session:
        job = session.scalars(select(Job)).one()
        job.status = JobStatus.PROCESSING
        job.started_at = utcnow() - timedelta(hours=2)

    assert reclaim_stale_jobs(database, settings) == 1
    with database.session() as session:
        job = session.scalars(select(Job)).one()
        assert job.status == JobStatus.PENDING
        assert job.started_at is None
    assert load(database, run_id).status == RunStatus.QUEUED


def test_reclaim_stale_job_at_attempt_cap_fails(database: Database, settings: Settings) -> None:
    run_id = enqueue(database, attempts=settings.job_max_attempts)
    with database.session() as session:
        job = session.scalars(select(Job)).one()
        job.status = JobStatus.PROCESSING
        job.started_at = utcnow() - timedelta(hours=2)

    assert reclaim_stale_jobs(database, settings) == 1
    with database.session() as session:
        job = session.scalars(select(Job)).one()
        assert job.status == JobStatus.FAILED
        assert job.finished_at is not None
    assert load(database, run_id).status == RunStatus.FAILED


def test_reclaim_ignores_recent_and_pending_jobs(database: Database, settings: Settings) -> None:
    enqueue(database)
    with database.session() as session:
        job = session.scalars(select(Job)).one()
        job.status = JobStatus.PROCESSING
        job.started_at = utcnow()
    assert reclaim_stale_jobs(database, settings) == 0


async def test_worker_loop_processes_job_and_stops(database: Database, settings: Settings) -> None:
    run_id = enqueue(database)
    called = asyncio.Event()

    async def processor(_run_id: str) -> None:
        called.set()

    worker = Worker(database, processor, settings, poll_seconds=0.01)
    await worker.start()
    assert worker.running is True
    await asyncio.wait_for(called.wait(), timeout=2)
    for _ in range(100):
        if load(database, run_id).status == RunStatus.SUCCEEDED:
            break
        await asyncio.sleep(0.01)
    await worker.stop()
    assert worker.running is False
    assert load(database, run_id).status == RunStatus.SUCCEEDED


async def test_worker_start_is_idempotent(database: Database, settings: Settings) -> None:
    async def processor(_run_id: str) -> None:
        return None

    worker = Worker(database, processor, settings, poll_seconds=0.01)
    await worker.start()
    first = worker._task
    await worker.start()
    assert worker._task is first
    await worker.stop()
    await worker.stop()


async def test_worker_cancels_processor_that_ignores_shutdown(
    database: Database, settings: Settings
) -> None:
    enqueue(database)
    entered = asyncio.Event()
    blocker = asyncio.Event()

    async def processor(_run_id: str) -> None:
        entered.set()
        await blocker.wait()

    worker = Worker(database, processor, settings, poll_seconds=0.01)
    await worker.start()
    await asyncio.wait_for(entered.wait(), timeout=2)
    await worker.stop(timeout=0.01)
    assert worker.running is False
    blocker.set()
