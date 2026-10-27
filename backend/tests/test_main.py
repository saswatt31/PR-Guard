from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.run_processor import RunProcessor
from app.settings import Settings


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "env": "test",
        "demo_mode": False,
    }


def test_cors_allows_configured_dashboard(client: TestClient) -> None:
    response = client.options(
        "/healthz",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_openapi_is_exposed(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "PR-Guard API"
    assert "/healthz" in spec["paths"]


def test_worker_enabled_builds_default_run_processor(
    settings: Settings, database: Database
) -> None:
    enabled = settings.model_copy(update={"worker_enabled": True})
    app = create_app(settings=enabled, database=database)

    assert isinstance(app.state.processor, RunProcessor)
