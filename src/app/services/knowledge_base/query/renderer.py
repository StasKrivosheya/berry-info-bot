from __future__ import annotations

from app.services.knowledge_base.query.types import AnswerBlock, QueryAnswerResult


def render_query_answer(result: QueryAnswerResult) -> str:
    parts: list[str] = []
    if result.summary:
        parts.append(result.summary)

    for block in result.blocks:
        rendered = _render_block(block)
        if rendered:
            parts.append(rendered)

    if result.sources:
        parts.append("Sources:\n" + "\n".join(f"- {source}" for source in result.sources))

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

