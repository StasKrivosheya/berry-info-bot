from __future__ import annotations

from dataclasses import dataclass

from app.services.knowledge_base.query.dto import AnswerResult
from app.services.knowledge_base.query.renderer import AnswerBlock, compose_answer_text


@dataclass(frozen=True, slots=True)
class AnswerDraft:
    summary: str | None
    blocks: tuple[AnswerBlock, ...] = ()
    sources: tuple[str, ...] = ()
    state: str = "answered"
    clarification_question: str | None = None
    debug_reason: str | None = None

    def to_answer_result(self) -> AnswerResult:
        return AnswerResult(
            state=self.state,
            answer_text=compose_answer_text(
                summary=self.summary,
                blocks=self.blocks,
                sources=self.sources,
            ),
            clarification_question=self.clarification_question,
            source_section_ids=self.sources,
            debug_reason=self.debug_reason,
        )
