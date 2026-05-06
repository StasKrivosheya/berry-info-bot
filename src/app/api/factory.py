from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.core.config import Settings

LifespanHandler = Callable[[FastAPI], AsyncIterator[None]]


def create_api_app(
    app_name: str,
    lifespan: LifespanHandler | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Create the FastAPI app and register operational routes."""

    app = FastAPI(
        title=app_name,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(health_router)
    return app
