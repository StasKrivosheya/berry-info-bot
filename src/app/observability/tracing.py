from __future__ import annotations

import time
from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Literal

TraceStatus = Literal["ok", "error", "skipped"]
TraceSpanEmitter = Callable[["TraceSpan"], None]

UNTRACKED_TRACE_ID = "untracked"
_CURRENT_TRACE_ID: ContextVar[str | None] = ContextVar("trace_id", default=None)


@dataclass(frozen=True, slots=True)
class TraceSpan:
    trace_id: str
    stage: str
    start_ms: int
    end_ms: int
    duration_ms: int
    status: TraceStatus
    meta: dict[str, object] = field(default_factory=dict)


def current_time_ms() -> int:
    return time.time_ns() // 1_000_000


def get_trace_id() -> str | None:
    return _CURRENT_TRACE_ID.get()


def set_trace_id(trace_id: str) -> Token[str | None]:
    return _CURRENT_TRACE_ID.set(trace_id)


def reset_trace_id(token: Token[str | None]) -> None:
    _CURRENT_TRACE_ID.reset(token)


def _resolve_trace_id(trace_id: str | None = None) -> str:
    return trace_id or get_trace_id() or UNTRACKED_TRACE_ID


def _emit_span(
    span: TraceSpan,
    *,
    emit: TraceSpanEmitter | None = None,
) -> None:
    if emit is not None:
        emit(span)
        return

    from app.observability.logger import log_trace_span

    log_trace_span(span)


class TraceStage:
    def __init__(
        self,
        stage: str,
        *,
        meta: dict[str, object] | None = None,
        trace_id: str | None = None,
        emit: TraceSpanEmitter | None = None,
    ) -> None:
        self._emit = emit
        self._meta = dict(meta or {})
        self._stage = stage
        self._start_ms = 0
        self._trace_id = _resolve_trace_id(trace_id)

    def __enter__(self) -> TraceStage:
        self._start_ms = current_time_ms()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        end_ms = current_time_ms()
        _emit_span(
            TraceSpan(
                trace_id=self._trace_id,
                stage=self._stage,
                start_ms=self._start_ms,
                end_ms=end_ms,
                duration_ms=max(0, end_ms - self._start_ms),
                status="error" if exc_type is not None else "ok",
                meta=dict(self._meta),
            ),
            emit=self._emit,
        )
        return False


def trace_stage(
    stage: str,
    *,
    meta: dict[str, object] | None = None,
    trace_id: str | None = None,
    emit: TraceSpanEmitter | None = None,
) -> TraceStage:
    return TraceStage(
        stage,
        meta=meta,
        trace_id=trace_id,
        emit=emit,
    )


def emit_skipped_span(
    stage: str,
    *,
    meta: dict[str, object] | None = None,
    trace_id: str | None = None,
    emit: TraceSpanEmitter | None = None,
) -> TraceSpan:
    timestamp_ms = current_time_ms()
    span = TraceSpan(
        trace_id=_resolve_trace_id(trace_id),
        stage=stage,
        start_ms=timestamp_ms,
        end_ms=timestamp_ms,
        duration_ms=0,
        status="skipped",
        meta=dict(meta or {}),
    )
    _emit_span(span, emit=emit)
    return span
