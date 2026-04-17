from __future__ import annotations

from typing import Protocol

from app.services.knowledge_base.query.dto import (
    EvidenceItem,
    EvidencePacket,
    LexicalHit,
    VectorHit,
)


class LexicalRetriever(Protocol):
    def search(self, *, query: str, max_results: int | None = None) -> tuple[LexicalHit, ...]:
        """Return lexical hits for a normalized query."""


class EmptyLexicalRetriever:
    def search(self, *, query: str, max_results: int | None = None) -> tuple[LexicalHit, ...]:
        del query, max_results
        return ()


def build_evidence_packet(
    *,
    vector_hits: tuple[VectorHit, ...],
    lexical_hits: tuple[LexicalHit, ...],
    token_budget: int | None = None,
) -> EvidencePacket:
    token_budget_used = 0
    truncation_applied = False
    items: list[EvidenceItem] = []

    for hit in vector_hits:
        title = str(hit.attributes.get("heading_path", "")).strip() or hit.section_id
        item = EvidenceItem(
            section_id=hit.section_id,
            source_type="vector",
            title=title,
            content=hit.text,
            score=hit.score,
        )
        item_tokens = _token_count(item.content)
        if token_budget is not None and token_budget_used + item_tokens > token_budget:
            truncation_applied = True
            break
        items.append(item)
        token_budget_used += item_tokens

    if not truncation_applied:
        for hit in lexical_hits:
            title = " > ".join(hit.heading_path) if hit.heading_path else hit.section_id
            item = EvidenceItem(
                section_id=hit.section_id,
                source_type="lexical",
                title=title or hit.section_id,
                content=hit.content,
                score=hit.bm25,
            )
            item_tokens = _token_count(item.content)
            if token_budget is not None and token_budget_used + item_tokens > token_budget:
                truncation_applied = True
                break
            items.append(item)
            token_budget_used += item_tokens

    return EvidencePacket(
        items=tuple(items),
        token_budget_used=token_budget_used,
        truncation_applied=truncation_applied,
    )


def _token_count(text: str) -> int:
    return len([token for token in text.split() if token])
