"""Database models.

Every table is documented in ARCHITECTURE.md. JSON columns are used only for
free-form per-run artefacts (config, step detail, coverage summary); relational
fields that the dashboard filters on stay as typed columns.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class JobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class TestStatus(StrEnum):
    # Prevent pytest from trying to collect this enum as a test class.
    __test__ = False

    PROPOSED = "proposed"
    VERIFIED = "verified"
    REJECTED = "rejected"


class Delivery(Base):
    """One GitHub webhook delivery. The unique delivery id makes retries no-ops."""

    __tablename__ = "deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    delivery_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    event: Mapped[str] = mapped_column(String(64))
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    runs: Mapped[list[Run]] = relationship(back_populates="delivery")


class Run(Base):
    """A single PR analysis run. One run belongs to one delivery."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    delivery_id: Mapped[str] = mapped_column(
        ForeignKey("deliveries.delivery_id", ondelete="CASCADE"), unique=True, index=True
    )
    repo_full_name: Mapped[str] = mapped_column(String(255), index=True)
    repo_owner: Mapped[str] = mapped_column(String(100))
    repo_name: Mapped[str] = mapped_column(String(200))
    pr_number: Mapped[int] = mapped_column(Integer)
    head_sha: Mapped[str] = mapped_column(String(64))
    base_sha: Mapped[str] = mapped_column(String(64))
    installation_id: Mapped[int] = mapped_column(Integer)
    sender_login: Mapped[str] = mapped_column(String(100))
    is_fork: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(String(20), default=RunStatus.QUEUED, index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    files_changed: Mapped[int] = mapped_column(Integer, default=0)
    functions_found: Mapped[int] = mapped_column(Integer, default=0)
    tests_generated: Mapped[int] = mapped_column(Integer, default=0)
    tests_verified: Mapped[int] = mapped_column(Integer, default=0)

    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    coverage_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    comment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    delivery: Mapped[Delivery] = relationship(back_populates="runs")
    job: Mapped[Job | None] = relationship(
        back_populates="run", uselist=False, cascade="all, delete-orphan"
    )
    steps: Mapped[list[AgentStep]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentStep.sequence"
    )
    tests: Mapped[list[GeneratedTest]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="GeneratedTest.created_at",
    )
    sandbox_runs: Mapped[list[SandboxExecution]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="SandboxExecution.created_at",
    )
    review: Mapped[CodeReview | None] = relationship(
        back_populates="run", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("repo_full_name", "head_sha", name="uq_runs_repo_head"),
        Index("ix_runs_repo_pr", "repo_full_name", "pr_number"),
    )


class Job(Base):
    """Durable queue row consumed by the in-process worker."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[Run] = relationship(back_populates="job")


class AgentStep(Base):
    """Trace of one graph node. Detail is redacted/summarised, never raw secrets."""

    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default=StepStatus.RUNNING)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="steps")


class GeneratedTest(Base):
    """LLM-written test file, only marked verified after sandbox execution."""

    __tablename__ = "generated_tests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(String(500))
    function_name: Mapped[str] = mapped_column(String(200))
    source_file: Mapped[str] = mapped_column(String(500))
    framework: Mapped[str] = mapped_column(String(20), default="vitest")
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=TestStatus.PROPOSED)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="tests")


class SandboxExecution(Base):
    """One sandbox invocation (install phase or test phase)."""

    __tablename__ = "sandbox_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    phase: Mapped[str] = mapped_column(String(20), default="test")
    image: Mapped[str] = mapped_column(String(200))
    command: Mapped[list[str]] = mapped_column(JSON, default=list)
    network_disabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20))
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    coverage: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="sandbox_runs")


class CodeReview(Base):
    """Short review pass, deliberately separate from test generation."""

    __tablename__ = "code_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    content: Mapped[str] = mapped_column(Text)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="review")
