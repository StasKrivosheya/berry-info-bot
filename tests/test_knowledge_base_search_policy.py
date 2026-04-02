from __future__ import annotations

from app.services.knowledge_base.retrieval.search_policy import apply_relevance_policy
from app.services.knowledge_base.types_openai import SearchHit


def _hit(*, score: float, file_id: str = "f1") -> SearchHit:
    return SearchHit(
        file_id=file_id,
        filename=f"{file_id}.md",
        score=score,
        attributes={"logical_id": file_id, "category": "faq", "language": "uk"},
        text="chunk",
    )


def test_apply_relevance_policy_returns_fallback_when_no_hits() -> None:
    response = apply_relevance_policy(hits=[], threshold=0.7, max_results=3)

    assert response.results == []
    assert response.top_score is None
    assert response.used_threshold == 0.7
    assert response.fallback_triggered is True
    assert response.fallback_message == "No relevant information found in the knowledge base."


def test_apply_relevance_policy_returns_fallback_when_top_score_below_threshold() -> None:
    hits = [_hit(score=0.69, file_id="f1"), _hit(score=0.95, file_id="f2")]
    response = apply_relevance_policy(hits=hits, threshold=0.7, max_results=3)

    # The policy relies on pre-sorted hits; if the first hit is below threshold it falls back.
    assert response.results == []
    assert response.top_score == 0.69
    assert response.used_threshold == 0.7
    assert response.fallback_triggered is True


def test_apply_relevance_policy_passes_hits_at_or_above_threshold_up_to_limit() -> None:
    hits = [
        _hit(score=0.9, file_id="f1"),
        _hit(score=0.8, file_id="f2"),
        _hit(score=0.7, file_id="f3"),
        _hit(score=0.65, file_id="f4"),
    ]
    response = apply_relevance_policy(hits=hits, threshold=0.7, max_results=2)

    assert response.fallback_triggered is False
    assert response.top_score == 0.9
    assert [item.file_id for item in response.results] == ["f1", "f2"]

