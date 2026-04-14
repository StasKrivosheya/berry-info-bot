from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.core.constants import DEFAULT_LOG_LEVEL
from app.observability.tracing import get_trace_id

UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")
STANDARD_LOG_RECORD_FIELDS = {
    *logging.makeLogRecord({}).__dict__.keys(),
    "asctime",
    "message",
}


class JsonLogFormatter(logging.Formatter):
    """Serialize log records as compact JSON for easier filtering/aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        trace_id = getattr(record, "trace_id", None) or get_trace_id()
        if trace_id is not None:
            payload["trace_id"] = trace_id

        for key, value in _iter_extra_fields(record).items():
            if key in payload:
                continue
            payload[key] = value

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


def _iter_extra_fields(record: logging.LogRecord) -> dict[str, object]:
    extras: dict[str, object] = {}
    for key, value in record.__dict__.items():
        if key in STANDARD_LOG_RECORD_FIELDS:
            continue
        extras[key] = _normalize_log_value(value)
    return extras


def _normalize_log_value(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _normalize_log_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list | set | frozenset):
        return [_normalize_log_value(item) for item in value]
    return str(value)
