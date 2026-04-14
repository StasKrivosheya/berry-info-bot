from __future__ import annotations

import logging
from collections.abc import Mapping
from uuid import uuid4

from aiogram import BaseMiddleware

from app.observability import (
    log_trace_request_finished,
    log_trace_request_started,
    reset_trace_id,
    set_trace_id,
)

logger = logging.getLogger(__name__)

TRACE_SOURCE_TELEGRAM = "telegram_update"
REQUEST_ID_HEADER_NAME = "X-Request-Id"


class TraceContextMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data: dict[str, object]):
        provided_trace_id = _resolve_request_id(data)
        trace_id = provided_trace_id or str(uuid4())
        request_id_source = "provided" if provided_trace_id else "generated"
        data["trace_id"] = trace_id

        token = set_trace_id(trace_id)
        event_meta = {
            "event_type": type(event).__name__,
        }
        log_trace_request_started(
            trace_id=trace_id,
            source=TRACE_SOURCE_TELEGRAM,
            request_id_source=request_id_source,
            meta=event_meta,
            logger=logger,
        )
        try:
            result = await handler(event, data)
        except Exception:
            log_trace_request_finished(
                trace_id=trace_id,
                source=TRACE_SOURCE_TELEGRAM,
                status="error",
                meta=event_meta,
                logger=logger,
            )
            raise
        else:
            log_trace_request_finished(
                trace_id=trace_id,
                source=TRACE_SOURCE_TELEGRAM,
                status="ok",
                meta=event_meta,
                logger=logger,
            )
            return result
        finally:
            reset_trace_id(token)


def _resolve_request_id(data: Mapping[str, object]) -> str | None:
    for mapping_key in ("headers", "request_headers", "http_headers"):
        candidate = _request_id_from_mapping(data.get(mapping_key))
        if candidate:
            return candidate

    for key in ("x_request_id", "request_id", "X-Request-Id"):
        candidate = _normalize_request_id(data.get(key))
        if candidate:
            return candidate
    return None


def _request_id_from_mapping(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None

    for key, header_value in value.items():
        if str(key).casefold() != REQUEST_ID_HEADER_NAME.casefold():
            continue
        candidate = _normalize_request_id(header_value)
        if candidate:
            return candidate
    return None


def _normalize_request_id(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
