"""FastAPI application. Binds to loopback only (see Procfile.dev)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import actors, border, events, health, reference
from app.core.config import get_settings
from app.core.logging import configure_logging

CLASSIFICATION = "UNCLASSIFIED — PUBLICLY AVAILABLE INFORMATION ONLY"


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings().log_level)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Cartel OSINT Dashboard API",
        version=__version__,
        description=CLASSIFICATION,
        lifespan=_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(reference.router)
    app.include_router(events.router)
    app.include_router(border.router)
    app.include_router(actors.router)
    return app


app = create_app()
