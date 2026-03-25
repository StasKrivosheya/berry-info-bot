from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from fastapi import FastAPI

from app.api.routes.health import router as health_router

LifespanHandler = Callable[[FastAPI], AsyncIterator[None]]


def create_api_app(
    app_name: str,
    lifespan: LifespanHandler | None = None,
) -> FastAPI:
    """Create the FastAPI app and register operational routes."""

    app = FastAPI(
        title=app_name,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    return app
