"""Cross-cutting constants used by multiple runtime layers."""

from __future__ import annotations

DEFAULT_APP_NAME = "berry-info-bot"
DEFAULT_APP_HOST = "0.0.0.0"
DEFAULT_APP_PORT = 8080
DEFAULT_LOG_LEVEL = "INFO"

# Local development uses .env.local first. .env stays as a backward-compatible fallback.
ENV_FILE_LOCAL = ".env.local"
ENV_FILE_FALLBACK = ".env"
ENV_FILE_DOCKER = ".env.docker"

DATABASE_URL_PREFIX = "postgresql+asyncpg://"
DATABASE_STARTUP_PROBE_QUERY = "SELECT 1"

HEALTH_ENDPOINT_PATH = "/health"
HEALTH_STATUS_OK = "ok"

POLLING_TASK_NAME = "telegram-polling"

WEBHOOK_SECRET_PATH_PLACEHOLDER = "/telegram/webhook/secret"
