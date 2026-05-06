"""Cross-cutting constants used by multiple runtime layers."""

from __future__ import annotations

DEFAULT_APP_NAME = "berry-info-bot"
DEFAULT_APP_HOST = "0.0.0.0"
DEFAULT_APP_PORT = 8080
DEFAULT_LOG_LEVEL = "INFO"

ENV_FILE = ".env"

HEALTH_ENDPOINT_PATH = "/health"
HEALTH_STATUS_OK = "ok"

POLLING_TASK_NAME = "telegram-polling"
