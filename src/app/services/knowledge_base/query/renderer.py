from __future__ import annotations

from dataclasses import dataclass

from app.services.knowledge_base.query.dto import AnswerResult


@dataclass(frozen=True, slots=True)
class AnswerBlock:
    title: str
    lines: tuple[str, ...] = ()
    body: str | None = None


def render_query_answer(result: AnswerResult) -> str:
    return result.answer_text


def compose_answer_text(
    *,
    summary: str | None,
    blocks: tuple[AnswerBlock, ...] = (),
    sources: tuple[str, ...] = (),
) -> str:
    parts: list[str] = []
    if summary:
        parts.append(summary)

    for block in blocks:
        rendered = _render_block(block)
        if rendered:
            parts.append(rendered)

    if sources:
        parts.append("Sources:\n" + "\n".join(f"- {source}" for source in sources))

    return "\n\n".join(part for part in parts if part)


def _render_block(block: AnswerBlock) -> str:
    parts: list[str] = []
    if block.title:
        parts.append(block.title)
    if block.lines:
        parts.append("\n".join(f"- {line}" for line in block.lines))
    elif block.body:
        parts.append(block.body)
    return "\n".join(parts).strip()
