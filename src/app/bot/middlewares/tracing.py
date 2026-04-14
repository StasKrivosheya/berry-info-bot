from __future__ import annotations

import logging
from collections.abc import Mapping
from types import SimpleNamespace
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
        event_meta = _build_event_meta(event)
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


def _build_event_meta(event: object) -> dict[str, object]:
    meta: dict[str, object] = {
        "event_type": type(event).__name__,
    }

    update_id = getattr(event, "update_id", None)
    if isinstance(update_id, int):
        meta["update_id"] = update_id

    user_id = _extract_user_id(event)
    if user_id is not None:
        meta["user_id"] = user_id

    chat_id = _extract_chat_id(event)
    if chat_id is not None:
        meta["chat_id"] = chat_id

    return meta


def _extract_user_id(event: object) -> int | None:
    direct_user = getattr(event, "from_user", None)
    user_id = getattr(direct_user, "id", None)
    if isinstance(user_id, int):
        return user_id

    for nested_attr in ("message", "callback_query", "edited_message", "channel_post"):
        nested = getattr(event, nested_attr, None)
        nested_user = getattr(nested, "from_user", None)
        nested_user_id = getattr(nested_user, "id", None)
        if isinstance(nested_user_id, int):
            return nested_user_id

    callback_query = getattr(event, "callback_query", None)
    callback_user_id = getattr(getattr(callback_query, "from_user", None), "id", None)
    if isinstance(callback_user_id, int):
        return callback_user_id

    return None


def _extract_chat_id(event: object) -> int | None:
    direct_chat = getattr(event, "chat", None)
    chat_id = getattr(direct_chat, "id", None)
    if isinstance(chat_id, int):
        return chat_id

    for nested_attr in ("message", "edited_message", "channel_post"):
        nested = getattr(event, nested_attr, None)
        nested_chat_id = getattr(getattr(nested, "chat", None), "id", None)
        if isinstance(nested_chat_id, int):
            return nested_chat_id

    callback_query = getattr(event, "callback_query", None)
    callback_message = getattr(callback_query, "message", None)
    callback_chat_id = getattr(getattr(callback_message, "chat", None), "id", None)
    if isinstance(callback_chat_id, int):
        return callback_chat_id

    if isinstance(event, SimpleNamespace):
        namespace_chat_id = getattr(getattr(event, "chat", None), "id", None)
        if isinstance(namespace_chat_id, int):
            return namespace_chat_id

    return None
