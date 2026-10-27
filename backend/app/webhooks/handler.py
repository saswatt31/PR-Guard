"""Business logic for GitHub pull_request events.

Kept separate from FastAPI so it can be unit-tested without HTTP and so duplicate
delivery / duplicate commit handling lives in one transaction.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import Database
from app.models import Delivery, Job, JobStatus, Run, RunStatus
from app.settings import Settings
from app.webhooks.payloads import PullRequestEvent, payload_is_fork

ALLOWED_ACTIONS = frozenset({"opened", "synchronize"})


class InvalidPayloadError(ValueError):
    """The request is authentic but not a usable pull_request event."""


@dataclass(frozen=True)
class WebhookOutcome:
    status: str
    run_id: str | None = None
    reason: str | None = None


def _duplicate_delivery(db: Database, delivery_id: str) -> WebhookOutcome | None:
    with db.session() as session:
        existing = session.scalars(
            select(Delivery).where(Delivery.delivery_id == delivery_id)
        ).first()
        if existing is None:
            return None
        run = session.scalars(select(Run).where(Run.delivery_id == delivery_id)).first()
        return WebhookOutcome(
            status="duplicate_delivery",
            run_id=run.id if run else None,
            reason="GitHub delivery id already processed",
        )


def process_event(
    db: Database,
    settings: Settings,
    *,
    event: str,
    payload: dict[str, Any],
    payload_bytes: bytes,
    delivery_id: str,
) -> WebhookOutcome:
    """Validate and enqueue one event. Never calls GitHub or an LLM."""

    if event == "ping":
        return WebhookOutcome(status="pong")
    if event != "pull_request":
        return WebhookOutcome(status="ignored_event", reason=f"unsupported event {event}")

    action = str(payload.get("action", ""))
    if action not in ALLOWED_ACTIONS:
        return WebhookOutcome(status="ignored_action", reason=f"unsupported action {action}")

    duplicate = _duplicate_delivery(db, delivery_id)
    if duplicate is not None:
        return duplicate

    try:
        pr_event = PullRequestEvent.model_validate(payload)
    except ValidationError as exc:
        # Do not echo the payload: it can contain user data and is attacker-controlled.
        raise InvalidPayloadError("pull_request payload is missing required fields") from exc

    is_fork = payload_is_fork(pr_event)
    body_hash = hashlib.sha256(payload_bytes).hexdigest()
    repo = pr_event.repository

    try:
        with db.session() as session:
            existing_run = session.scalars(
                select(Run).where(
                    Run.repo_full_name == repo.full_name,
                    Run.head_sha == pr_event.pull_request.head.sha,
                )
            ).first()
            delivery = Delivery(
                delivery_id=delivery_id,
                event=event,
                action=action,
                payload_sha256=body_hash,
            )
            session.add(delivery)

            if existing_run is not None:
                return WebhookOutcome(
                    status="duplicate_commit",
                    run_id=existing_run.id,
                    reason="this head commit was already analysed",
                )

            run = Run(
                delivery_id=delivery_id,
                repo_full_name=repo.full_name,
                repo_owner=repo.owner.login,
                repo_name=repo.name,
                pr_number=pr_event.number,
                head_sha=pr_event.pull_request.head.sha,
                base_sha=pr_event.pull_request.base.sha,
                installation_id=pr_event.installation.id,
                sender_login=pr_event.sender.login,
                is_fork=is_fork,
                config={},
            )
            delivery.runs.append(run)

            if is_fork and not settings.allow_fork_prs:
                run.status = RunStatus.SKIPPED
                run.summary = "Fork PR skipped: fork PRs are disabled by policy."
                session.flush()
                return WebhookOutcome(
                    status="skipped_fork",
                    run_id=run.id,
                    reason="fork pull requests are disabled by default",
                )

            job = Job(status=JobStatus.PENDING)
            run.job = job
            run.status = RunStatus.QUEUED
            session.flush()
            return WebhookOutcome(status="queued", run_id=run.id)
    except IntegrityError:
        # A concurrent delivery raced us. The unique index is the source of truth.
        duplicate = _duplicate_delivery(db, delivery_id)
        if duplicate is not None:
            return duplicate
        raise
