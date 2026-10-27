"""FastAPI entrypoint. Wiring for webhooks and dashboard routes lands in later phases."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.db import Database
from app.settings import Settings, get_settings


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    cfg = settings or get_settings()
    db = database or Database(cfg.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db.create_all()
        yield
        app.state.db.dispose()

    app = FastAPI(
        title="PR-Guard API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.db = db

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
