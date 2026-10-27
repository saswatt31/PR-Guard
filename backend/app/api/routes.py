"""Read-only run API consumed by the Next.js dashboard.

There are deliberately no mutation endpoints. The webhook and worker own all writes;
the dashboard is an observability surface, not a second control plane.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models import Run, RunStatus
from app.schemas import DemoInfo, RunDetail, RunList, RunStats, RunSummary

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/runs", response_model=RunList)
def list_runs(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: RunStatus | None = None,
    repo: Annotated[str | None, Query(max_length=255)] = None,
) -> RunList:
    """Return newest runs first, with optional status and repository filters."""

    filters = []
    if status is not None:
        filters.append(Run.status == status)
    if repo and repo.strip():
        filters.append(
            func.lower(Run.repo_full_name).contains(repo.strip().lower(), autoescape=True)
        )

    with request.app.state.db.session() as session:
        total = session.scalar(select(func.count()).select_from(Run).where(*filters)) or 0
        runs = session.scalars(
            select(Run)
            .where(*filters)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        items = [RunSummary.model_validate(run) for run in runs]

    return RunList(items=items, total=int(total), limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(request: Request, run_id: str) -> RunDetail:
    """Return one run and all of its child records."""

    with request.app.state.db.session() as session:
        run = session.scalar(
            select(Run)
            .where(Run.id == run_id)
            .options(
                selectinload(Run.steps),
                selectinload(Run.tests),
                selectinload(Run.sandbox_runs),
                selectinload(Run.review),
            )
        )
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return RunDetail.model_validate(run)


@router.get("/stats", response_model=RunStats)
def stats(request: Request) -> RunStats:
    """Aggregate counters for the dashboard cards."""

    with request.app.state.db.session() as session:
        grouped = dict(session.execute(select(Run.status, func.count()).group_by(Run.status)).all())
        tests = session.execute(
            select(func.sum(Run.tests_generated), func.sum(Run.tests_verified))
        ).one()
        cost = session.scalar(select(func.sum(Run.cost_usd))) or 0.0
        coverage = session.scalar(select(func.avg(Run.coverage_delta)))
        duration = session.scalar(select(func.avg(Run.duration_ms)))

    return RunStats(
        total_runs=sum(int(value) for value in grouped.values()),
        queued=int(grouped.get(RunStatus.QUEUED, 0)),
        running=int(grouped.get(RunStatus.RUNNING, 0)),
        succeeded=int(grouped.get(RunStatus.SUCCEEDED, 0)),
        failed=int(grouped.get(RunStatus.FAILED, 0)),
        skipped=int(grouped.get(RunStatus.SKIPPED, 0)),
        tests_generated=int(tests[0] or 0),
        tests_verified=int(tests[1] or 0),
        total_cost_usd=round(float(cost), 6),
        avg_coverage_delta=(round(float(coverage), 2) if coverage is not None else None),
        avg_duration_ms=(int(duration) if duration is not None else None),
    )


@router.get("/demo", response_model=DemoInfo)
def demo_info(request: Request) -> DemoInfo:
    """Expose whether this deployment is the public read-only demo."""

    with request.app.state.db.session() as session:
        count = session.scalar(select(func.count()).select_from(Run)) or 0
    return DemoInfo(enabled=request.app.state.settings.demo_mode, run_count=int(count))
