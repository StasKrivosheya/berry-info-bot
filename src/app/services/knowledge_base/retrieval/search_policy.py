from __future__ import annotations

from typing import Any

from app.services.knowledge_base.retrieval.attributes import normalize_attributes
from app.services.knowledge_base.types_openai import (
    NO_RELEVANT_INFO_FALLBACK,
    SearchHit,
    SearchResponse,
)


def normalize_search_hits(raw_results: list[Any]) -> list[SearchHit]:
    """Convert raw vector-store search entries into deterministic SearchHit objects."""

    hits = [
        SearchHit(
            file_id=str(item.file_id),
            filename=str(item.filename),
            score=float(item.score),
            attributes=normalize_attributes(getattr(item, "attributes", None)),
            text=_extract_text(getattr(item, "content", [])),
        )
        for item in raw_results
    ]
    hits.sort(key=lambda hit: (-hit.score, hit.file_id, hit.filename))
    return hits


def apply_relevance_policy(
    *,
    hits: list[SearchHit],
    threshold: float,
    max_results: int,
) -> SearchResponse:
    """Apply top-score gate and threshold filtering with deterministic fallback semantics."""

    top_score = hits[0].score if hits else None
    fallback_triggered = top_score is None or top_score < threshold
    if fallback_triggered:
        return SearchResponse(
            results=[],
            top_score=top_score,
            used_threshold=threshold,
            fallback_triggered=True,
            fallback_message=NO_RELEVANT_INFO_FALLBACK,
        )

    filtered_results = [hit for hit in hits if hit.score >= threshold][:max_results]
    return SearchResponse(
        results=filtered_results,
        top_score=top_score,
        used_threshold=threshold,
        fallback_triggered=False,
        fallback_message=None,
    )


def _extract_text(content_items: object) -> str:
    if not isinstance(content_items, list):
        return ""

    chunks: list[str] = []
    for item in content_items:
        item_type = getattr(item, "type", None)
        item_text = getattr(item, "text", None)
        if item_type == "text" and isinstance(item_text, str) and item_text.strip():
            chunks.append(item_text.strip())
    return "\n\n".join(chunks)



