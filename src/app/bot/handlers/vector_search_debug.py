from __future__ import annotations

from aiogram.filters import CommandObject

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


def format_search_messages(query: str, response: SearchResponse) -> list[str]:
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
        rendered.append(
            _render_message(
                service_lines=_render_service_lines(
                    query=query,
                    response=response,
                    hit=hit,
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
    index: int,
    total: int,
) -> list[str]:
    logical_id = hit.attributes.get("logical_id", "")
    category = hit.attributes.get("category", "")
    return [
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


def _render_message(*, service_lines: list[str], text: str) -> str:
    normalized_text = text.strip()
    text_block = normalized_text if normalized_text else "(empty text result)"
    return (
        "\n".join(service_lines)
        + "\n\n"
        + "--------------------"
        + "\n\n"
        + "Text:"
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
