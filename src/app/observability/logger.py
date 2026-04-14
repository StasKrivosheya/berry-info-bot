from __future__ import annotations

import logging

from app.observability.tracing import TraceSpan

LOG_EVENT_TRACE_REQUEST_STARTED = "trace_request_started"
LOG_EVENT_TRACE_REQUEST_FINISHED = "trace_request_finished"
LOG_EVENT_TRACE_SPAN = "trace_span"


def _log_event(
    event: str,
    *,
    logger: logging.Logger | None = None,
    level: int = logging.INFO,
    message: str | None = None,
    **fields: object,
) -> None:
    payload = {"event": event}
    payload.update({key: value for key, value in fields.items() if value is not None})
    (logger or logging.getLogger(__name__)).log(
        level,
        message or event,
        extra=payload,
    )


def log_trace_request_started(
    *,
    trace_id: str,
    source: str,
    request_id_source: str,
    meta: dict[str, object] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    _log_event(
        LOG_EVENT_TRACE_REQUEST_STARTED,
        logger=logger,
        trace_id=trace_id,
        source=source,
        request_id_source=request_id_source,
        meta=dict(meta or {}),
    )


def log_trace_request_finished(
    *,
    trace_id: str,
    source: str,
    status: str,
    meta: dict[str, object] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    _log_event(
        LOG_EVENT_TRACE_REQUEST_FINISHED,
        logger=logger,
        trace_id=trace_id,
        source=source,
        status=status,
        meta=dict(meta or {}),
    )


def log_trace_span(
    span: TraceSpan,
    *,
    logger: logging.Logger | None = None,
) -> None:
    _log_event(
        LOG_EVENT_TRACE_SPAN,
        logger=logger,
        trace_id=span.trace_id,
        stage=span.stage,
        start_ms=span.start_ms,
        end_ms=span.end_ms,
        duration_ms=span.duration_ms,
        status=span.status,
        meta=dict(span.meta),
    )
