import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

import app.webhooks.handler as handler_module
from app.db import Database
from app.models import Delivery, Job, JobStatus, Run, RunStatus
from app.settings import Settings
from app.webhooks.handler import WebhookOutcome, _duplicate_commit, process_event
from app.webhooks.signature import sign_payload
from tests.factories import pull_request_payload

SECRET = "test-secret"


def post_webhook(
    client: TestClient,
    payload: dict,
    *,
    event: str = "pull_request",
    delivery_id: str = "delivery-1",
    secret: str = SECRET,
    signature: str | None = None,
):
    body = json.dumps(payload).encode()
    headers = {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery_id,
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature or sign_payload(body, secret),
    }
    return client.post("/webhooks/github", content=body, headers=headers)


def runs(database: Database) -> list[Run]:
    with database.session() as session:
        return list(session.scalars(select(Run).options(selectinload(Run.job))).all())


def test_valid_webhook_enqueues_run_and_job(client: TestClient, database: Database) -> None:
    response = post_webhook(client, pull_request_payload())
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    run = runs(database)[0]
    assert body["run_id"] == run.id
    assert run.status == RunStatus.QUEUED
    assert run.job is not None
    assert run.job.status == JobStatus.PENDING
    assert run.repo_owner == "acme"
    assert run.repo_name == "demo"
    assert run.is_fork is False


def test_invalid_signature_rejected_before_any_side_effect(
    client: TestClient, database: Database
) -> None:
    body = json.dumps(pull_request_payload()).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "bad-sig",
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
        },
    )
    assert response.status_code == 401
    assert runs(database) == []


def test_missing_and_malformed_signature_rejected(client: TestClient) -> None:
    body = json.dumps(pull_request_payload()).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "d1"},
    )
    assert response.status_code == 401

    response = post_webhook(client, pull_request_payload(), signature="sha1=abc")
    assert response.status_code == 401


def test_missing_event_headers_rejected_after_valid_signature(client: TestClient) -> None:
    body = json.dumps(pull_request_payload()).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": sign_payload(body, SECRET)},
    )
    assert response.status_code == 400


def test_invalid_json_rejected(client: TestClient) -> None:
    body = b"{not-json"
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "bad-json",
            "X-Hub-Signature-256": sign_payload(body, SECRET),
        },
    )
    assert response.status_code == 400


def test_non_object_json_rejected(client: TestClient) -> None:
    body = b"[1,2,3]"
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "array-json",
            "X-Hub-Signature-256": sign_payload(body, SECRET),
        },
    )
    assert response.status_code == 400


def test_ping_is_acknowledged(client: TestClient, database: Database) -> None:
    response = post_webhook(client, {"zen": "hi"}, event="ping", delivery_id="ping-1")
    assert response.status_code == 200
    assert response.json() == {"status": "pong"}
    assert runs(database) == []


def test_unsupported_event_is_ignored(client: TestClient) -> None:
    response = post_webhook(client, {"action": "created"}, event="issue_comment")
    assert response.status_code == 202
    assert response.json()["status"] == "ignored_event"


def test_unsupported_action_is_ignored(client: TestClient) -> None:
    response = post_webhook(client, pull_request_payload(action="closed"), delivery_id="closed-1")
    assert response.status_code == 202
    assert response.json()["status"] == "ignored_action"


def test_invalid_payload_returns_400(client: TestClient) -> None:
    payload = pull_request_payload()
    del payload["installation"]
    response = post_webhook(client, payload, delivery_id="bad-payload")
    assert response.status_code == 400
    assert "required fields" in response.json()["detail"]


def test_fork_pr_is_skipped_and_recorded(client: TestClient, database: Database) -> None:
    response = post_webhook(client, pull_request_payload(fork=True), delivery_id="fork-1")
    assert response.status_code == 202
    assert response.json()["status"] == "skipped_fork"
    run = runs(database)[0]
    assert run.status == RunStatus.SKIPPED
    assert run.is_fork is True
    assert run.job is None


def test_fork_pr_can_be_opted_in(settings: Settings, database: Database) -> None:
    from app.main import create_app

    settings.allow_fork_prs = True
    app = create_app(settings=settings, database=database)
    with TestClient(app) as client:
        response = post_webhook(client, pull_request_payload(fork=True), delivery_id="fork-allowed")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    run = runs(database)[0]
    assert run.job is not None


def test_duplicate_delivery_is_idempotent(client: TestClient, database: Database) -> None:
    first = post_webhook(client, pull_request_payload(), delivery_id="same")
    second = post_webhook(client, pull_request_payload(), delivery_id="same")
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["status"] == "duplicate_delivery"
    assert second.json()["run_id"] == first.json()["run_id"]
    assert len(runs(database)) == 1
    with database.session() as session:
        assert len(session.scalars(select(Delivery)).all()) == 1


def test_same_commit_with_new_delivery_does_not_rerun(
    client: TestClient, database: Database
) -> None:
    first = post_webhook(client, pull_request_payload(), delivery_id="first")
    second = post_webhook(client, pull_request_payload(), delivery_id="second")
    assert second.json()["status"] == "duplicate_commit"
    assert second.json()["run_id"] == first.json()["run_id"]
    assert len(runs(database)) == 1


def test_commit_lookup_is_scoped_to_repo_and_sha(client: TestClient, database: Database) -> None:
    first = post_webhook(client, pull_request_payload(), delivery_id="lookup-1")
    existing = _duplicate_commit(database, "acme/demo", "a" * 40)
    assert existing is not None
    assert existing.status == "duplicate_commit"
    assert existing.run_id == first.json()["run_id"]
    assert _duplicate_commit(database, "acme/other", "a" * 40) is None
    assert _duplicate_commit(database, "acme/demo", "f" * 40) is None


class _FailOnEnter:
    """Simulate the INSERT losing a unique-constraint race."""

    def __enter__(self):
        raise IntegrityError("INSERT INTO runs", {}, Exception("simulated race"))

    def __exit__(self, *_exc) -> bool:
        return False


def test_integrity_error_race_returns_existing_delivery(
    database: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    winner = WebhookOutcome(status="duplicate_delivery", run_id="run-race")
    calls = {"count": 0}

    def lookup_delivery(_db: Database, _delivery_id: str) -> WebhookOutcome | None:
        calls["count"] += 1
        return None if calls["count"] == 1 else winner

    monkeypatch.setattr(handler_module, "_duplicate_delivery", lookup_delivery)
    monkeypatch.setattr(database, "session", lambda: _FailOnEnter())

    outcome = process_event(
        database,
        settings,
        event="pull_request",
        payload=pull_request_payload(),
        payload_bytes=b"{}",
        delivery_id="race-delivery",
    )

    assert outcome is winner
    assert calls["count"] == 2


def test_integrity_error_race_returns_existing_commit(
    database: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    winner = WebhookOutcome(status="duplicate_commit", run_id="run-race")
    monkeypatch.setattr(handler_module, "_duplicate_delivery", lambda *_: None)
    monkeypatch.setattr(handler_module, "_duplicate_commit", lambda *_: winner)
    monkeypatch.setattr(database, "session", lambda: _FailOnEnter())

    outcome = process_event(
        database,
        settings,
        event="pull_request",
        payload=pull_request_payload(),
        payload_bytes=b"{}",
        delivery_id="race-delivery",
    )

    assert outcome is winner


def test_integrity_error_without_winner_is_reraised(
    database: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(handler_module, "_duplicate_delivery", lambda *_: None)
    monkeypatch.setattr(handler_module, "_duplicate_commit", lambda *_: None)
    monkeypatch.setattr(database, "session", lambda: _FailOnEnter())

    with pytest.raises(IntegrityError):
        process_event(
            database,
            settings,
            event="pull_request",
            payload=pull_request_payload(),
            payload_bytes=b"{}",
            delivery_id="race-delivery",
        )


def test_webhook_body_size_limit(settings: Settings, database: Database) -> None:
    from app.main import create_app

    settings.max_webhook_bytes = 10
    app = create_app(settings=settings, database=database)
    with TestClient(app) as client:
        response = post_webhook(client, pull_request_payload(), delivery_id="big")
    assert response.status_code == 413


def test_production_rejects_default_webhook_secret(settings: Settings, database: Database) -> None:
    import pytest

    from app.main import create_app

    settings.app_env = "production"
    settings.github_webhook_secret = "change-me"
    with pytest.raises(RuntimeError, match="GITHUB_WEBHOOK_SECRET"):
        create_app(settings=settings, database=database)


async def test_webhook_to_worker_integration(
    client: TestClient, database: Database, settings: Settings
) -> None:
    from app.queue.worker import Worker

    response = post_webhook(client, pull_request_payload(), delivery_id="integration")
    run_id = response.json()["run_id"]
    processed: list[str] = []

    async def processor(claimed_run_id: str) -> None:
        processed.append(claimed_run_id)

    worker = Worker(database, processor, settings)
    assert await worker.process_once() is True
    assert processed == [run_id]
    run = runs(database)[0]
    assert run.status == RunStatus.SUCCEEDED
    with database.session() as session:
        job = session.scalars(select(Job)).one()
        assert job.status == JobStatus.DONE
