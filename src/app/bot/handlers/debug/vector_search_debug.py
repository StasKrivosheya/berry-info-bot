from __future__ import annotations

from aiogram.filters import CommandObject

from app.services.knowledge_base.query.types import SearchHitDebugContext
from app.services.knowledge_base.types_openai import (
    NO_RELEVANT_INFO_FALLBACK,
    SearchHit,
    SearchResponse,
)

VS_COMMAND_NAME = "vs"
VS_USAGE_TEXT = "Usage: /vs <your question>"
VS_ERROR_TEXT = "Vector search is temporarily unavailable. Please try again later."
TELEGRAM_MESSAGE_CHAR_LIMIT = 3900


def extract_query_text(command: CommandObject) -> str:
    """Extract and normalize free-form query payload from /vs command."""

    return (command.args or "").strip()


def format_search_messages(
    query: str,
    response: SearchResponse,
    *,
    hit_contexts: list[SearchHitDebugContext | None] | None = None,
) -> list[str]:
    """Render search response as one message per finding with two clear blocks."""

    if not response.results:
        service_lines = [
            "Service:",
            f"query={query}",
            (
                "result_count=0 "
                f"(threshold={response.used_threshold}, top_score={response.top_score}, "
                f"fallback_triggered={response.fallback_triggered})"
            ),
        ]
        text_block = response.fallback_message or NO_RELEVANT_INFO_FALLBACK
        return [_render_message(service_lines=service_lines, text=text_block)]

    total = len(response.results)
    rendered: list[str] = []
    for index, hit in enumerate(response.results, start=1):
        hit_context = None
        if hit_contexts is not None and index - 1 < len(hit_contexts):
            hit_context = hit_contexts[index - 1]
        rendered.append(
            _render_message(
                service_lines=_render_service_lines(
                    query=query,
                    response=response,
                    hit=hit,
                    hit_context=hit_context,
                    index=index,
                    total=total,
                ),
                text=hit.text,
            )
        )
    return rendered


def _render_service_lines(
    *,
    query: str,
    response: SearchResponse,
    hit: SearchHit,
    hit_context: SearchHitDebugContext | None,
    index: int,
    total: int,
) -> list[str]:
    logical_id = hit.attributes.get("logical_id", "")
    category = hit.attributes.get("category", "")
    lines = [
        "Service:",
        f"query={query}",
        f"result={index}/{total}",
        f"score={hit.score:.4f}",
        f"file={hit.filename}",
        f"file_id={hit.file_id}",
        f"logical_id={logical_id}",
        f"category={category}",
        (
            f"threshold={response.used_threshold} "
            f"top_score={response.top_score} "
            f"fallback_triggered={response.fallback_triggered}"
        ),
    ]
    if hit_context is not None:
        if hit_context.source_file:
            lines.append(f"source={hit_context.source_file}")
        if hit_context.heading_path:
            lines.append(f"heading_path={' > '.join(hit_context.heading_path)}")
    return lines


def _render_message(*, service_lines: list[str], text: str, body_label: str = "Text") -> str:
    normalized_text = text.strip()
    text_block = normalized_text if normalized_text else "(empty text result)"
    return (
        "\n".join(service_lines)
        + "\n\n"
        + "--------------------"
        + "\n\n"
        + body_label
        + ":"
        + "\n"
        + text_block
    )


def split_for_telegram(text: str, *, limit: int = TELEGRAM_MESSAGE_CHAR_LIMIT) -> list[str]:
    """Split long text into Telegram-safe chunks while preferring line boundaries."""

    if limit <= 0:
        msg = "limit must be positive"
        raise ValueError(msg)

    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    current = ""
    for raw_line in text.splitlines(keepends=True):
        if len(raw_line) > limit:
            if current:
                parts.append(current)
                current = ""
            start = 0
            while start < len(raw_line):
                parts.append(raw_line[start : start + limit])
                start += limit
            continue

        if len(current) + len(raw_line) > limit:
            parts.append(current)
            current = raw_line
            continue

        current += raw_line

    if current:
        parts.append(current)

    return parts

