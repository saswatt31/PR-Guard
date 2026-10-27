"""Pydantic response models for the dashboard API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sequence: int
    node: str
    status: str
    attempt: int
    summary: str
    detail: dict[str, Any]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    error: str | None
    created_at: datetime


class GeneratedTestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_path: str
    function_name: str
    source_file: str
    framework: str
    content: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime


class SandboxExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    phase: str
    image: str
    command: list[str]
    network_disabled: bool
    status: str
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    stdout: str
    stderr: str
    coverage: dict[str, Any] | None
    created_at: datetime


class CodeReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content: str
    cost_usd: float
    created_at: datetime


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    repo_full_name: str
    pr_number: int
    head_sha: str
    status: str
    summary: str | None
    files_changed: int
    functions_found: int
    tests_generated: int
    tests_verified: int
    cost_usd: float
    coverage_delta: float | None
    duration_ms: int | None
    created_at: datetime
    updated_at: datetime


class RunDetail(RunSummary):
    delivery_id: str
    base_sha: str
    installation_id: int
    sender_login: str
    is_fork: bool
    config: dict[str, Any]
    error: str | None
    llm_calls: int
    input_tokens: int
    output_tokens: int
    coverage_before: float | None
    coverage_after: float | None
    comment_id: int | None
    comment_url: str | None
    steps: list[StepOut]
    tests: list[GeneratedTestOut]
    sandbox_runs: list[SandboxExecutionOut]
    review: CodeReviewOut | None


class DemoInfo(BaseModel):
    enabled: bool
    run_count: int
