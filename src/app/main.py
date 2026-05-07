from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from app.api.factory import create_api_app
from app.bootstrap.lifespan import create_app_lifespan
from app.core.config import get_settings
from app.core.logging import configure_logging

UVICORN_APP_FACTORY_TARGET = "app.main:create_app"


def create_app() -> FastAPI:
    """Build and return the HTTP app with lifecycle-managed bot polling."""

    settings = get_settings()
    configure_logging(settings.log_level)
    return create_api_app(
        app_name=settings.app_name,
        lifespan=create_app_lifespan(settings),
        settings=settings,
    )


def run() -> None:
    """Run uvicorn using factory mode so settings are loaded once per process."""

    settings = get_settings()
    uvicorn.run(
        UVICORN_APP_FACTORY_TARGET,
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        log_config=None,
    )


if __name__ == "__main__":
    run()
