"""Durable SQLite-backed job queue and its single in-process worker.

The queue row is inserted in the same transaction as the run. The worker claims one
pending row at a time, so a restart cannot lose work and the webhook response stays fast.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import Database
from app.models import Job, JobStatus, Run, RunStatus, utcnow
from app.settings import Settings

logger = logging.getLogger(__name__)

RunProcessor = Callable[[str], Awaitable[None]]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _elapsed_ms(start: datetime | None, end: datetime | None = None) -> int:
    start_utc = _as_utc(start)
    if start_utc is None:
        return 0
    end_utc = _as_utc(end) or utcnow()
    return max(0, int((end_utc - start_utc).total_seconds() * 1000))


def claim_next_job(db: Database) -> Job | None:
    """Atomically move the oldest pending job to processing.

    SQLite has a single writer, so this short transaction is sufficient for one worker.
    A Postgres deployment would use ``FOR UPDATE SKIP LOCKED`` instead.
    """

    with db.session() as session:
        job = session.scalars(
            select(Job)
            .where(Job.status == JobStatus.PENDING)
            .order_by(Job.created_at, Job.id)
            .limit(1)
        ).first()
        if job is None:
            return None
        job.status = JobStatus.PROCESSING
        job.attempts += 1
        job.started_at = utcnow()
        run = session.get(Run, job.run_id)
        if run is not None:
            run.status = RunStatus.RUNNING
            run.error = None
        session.flush()
        session.expunge(job)
        return job


def _finish_job(db: Database, job_id: str, error: str | None) -> None:
    with db.session() as session:
        job = session.get(Job, job_id)
        if job is None:  # pragma: no cover - only if a row is deleted concurrently
            return
        run = session.get(Run, job.run_id)
        job.finished_at = utcnow()
        job.last_error = error
        if run is not None:
            run.duration_ms = _elapsed_ms(job.started_at, job.finished_at)
        if error is None:
            job.status = JobStatus.DONE
            if run is not None and run.status not in {RunStatus.FAILED, RunStatus.SKIPPED}:
                run.status = RunStatus.SUCCEEDED
        else:
            job.status = JobStatus.FAILED
            if run is not None:
                run.status = RunStatus.FAILED
                run.error = error[:4000]


def reclaim_stale_jobs(db: Database, settings: Settings) -> int:
    """Recover jobs left in ``processing`` by a crashed process.

    A job that exceeded the worker attempt cap is failed instead of retried, because a
    poison PR (or a deterministic crash) should not loop forever.
    """

    stale_after = (
        settings.sandbox_install_timeout_seconds
        + settings.sandbox_timeout_seconds * settings.job_max_attempts
        + 120
    )
    cutoff = utcnow() - timedelta(seconds=stale_after)
    reclaimed = 0
    with db.session() as session:
        jobs = session.scalars(select(Job).where(Job.status == JobStatus.PROCESSING)).all()
        for job in jobs:
            started = _as_utc(job.started_at)
            if started is not None and started >= cutoff:
                continue
            run = session.get(Run, job.run_id)
            if job.attempts >= settings.job_max_attempts:
                job.status = JobStatus.FAILED
                job.finished_at = utcnow()
                job.last_error = "worker crashed and attempt cap was reached"
                if run is not None:
                    run.status = RunStatus.FAILED
                    run.error = "worker crashed and attempt cap was reached"
            else:
                job.status = JobStatus.PENDING
                job.started_at = None
                if run is not None:
                    run.status = RunStatus.QUEUED
            reclaimed += 1
    return reclaimed


class Worker:
    def __init__(
        self,
        db: Database,
        processor: RunProcessor,
        settings: Settings,
        *,
        poll_seconds: float | None = None,
    ) -> None:
        self.db = db
        self.processor = processor
        self.settings = settings
        self.poll_seconds = (
            poll_seconds if poll_seconds is not None else settings.worker_poll_seconds
        )
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def process_once(self) -> bool:
        job = claim_next_job(self.db)
        if job is None:
            return False
        try:
            await self.processor(job.run_id)
        except asyncio.CancelledError:
            # Let the loop exit; the stale-job reclaimer handles this run on restart.
            raise
        except Exception as exc:  # noqa: BLE001 - run failures must be recorded, not crash worker
            logger.exception("run %s failed", job.run_id)
            _finish_job(self.db, job.id, f"{type(exc).__name__}: {exc}")
            return True
        _finish_job(self.db, job.id, None)
        return True

    async def _loop(self) -> None:
        try:
            reclaimed = reclaim_stale_jobs(self.db, self.settings)
            if reclaimed:
                logger.warning("reclaimed %s stale job(s)", reclaimed)
            while not self._stop.is_set():
                processed = await self.process_once()
                if not processed:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            logger.info("worker cancelled")
            raise

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="prguard-worker")
        logger.info("worker started (poll=%ss)", self.poll_seconds)

    async def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._task, timeout=timeout)
        except TimeoutError:  # pragma: no cover - only when a processor ignores shutdown
            logger.warning("worker did not stop within %ss; cancelling", timeout)
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        finally:
            self._task = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()
