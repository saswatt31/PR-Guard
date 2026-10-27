"""FastAPI entrypoint. Wiring for webhooks and dashboard routes lands in later phases."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import router as api_router
from app.db import Database
from app.queue.worker import RunProcessor, Worker
from app.run_processor import RunProcessor as GitHubRunProcessor
from app.settings import Settings, get_settings
from app.webhooks.routes import router as webhook_router


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    processor: RunProcessor | None = None,
) -> FastAPI:
    cfg = settings or get_settings()
    db = database or Database(cfg.database_url)
    if cfg.app_env == "production" and cfg.github_webhook_secret in {"", "change-me"}:
        raise RuntimeError("GITHUB_WEBHOOK_SECRET must be set in production")
    if processor is None and cfg.worker_enabled:
        processor = GitHubRunProcessor(db, cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db.create_all()
        if cfg.worker_enabled and processor is not None:
            app.state.worker = Worker(app.state.db, processor, cfg)
            await app.state.worker.start()
        yield
        worker: Worker | None = getattr(app.state, "worker", None)
        if worker is not None:
            await worker.stop()
        app.state.db.dispose()

    app = FastAPI(
        title="PR-Guard API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.db = db
    app.state.processor = processor
    app.state.worker = None
    app.include_router(webhook_router)
    app.include_router(api_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["system"])
    def healthz() -> dict[str, object]:
        return {
            "status": "ok",
            "version": __version__,
            "env": cfg.app_env,
            "demo_mode": cfg.demo_mode,
        }

    return app


app = create_app()
