from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from app.core.constants import DEFAULT_LOG_LEVEL

UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")


class JsonLogFormatter(logging.Formatter):
    """Serialize log records as compact JSON for easier filtering/aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True)


def configure_logging(level: str = DEFAULT_LOG_LEVEL) -> None:
    """Configure a single structured logger pipeline for app and uvicorn."""

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel((level or DEFAULT_LOG_LEVEL).upper())

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root_logger.addHandler(handler)

    # Let uvicorn loggers flow into the same structured root handler.
    for logger_name in UVICORN_LOGGER_NAMES:
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True
