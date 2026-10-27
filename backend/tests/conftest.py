"""Shared pytest fixtures. Every test gets its own SQLite file and temp directory."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        worker_enabled=False,
        sandbox_mode="local",
        github_webhook_secret="test-secret",
        llm_provider="fake",
        github_app_id="12345",
    )


@pytest.fixture
def database(settings: Settings) -> Iterator[Database]:
    db = Database(settings.database_url)
    db.create_all()
    yield db
    db.dispose()


@pytest.fixture
def app(settings: Settings, database: Database):
    return create_app(settings=settings, database=database)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
