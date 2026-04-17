from __future__ import annotations

from dataclasses import dataclass

from app.services.knowledge_base.query.dto import VectorHit
from app.services.knowledge_base.query.types import QueryRetrievalExecutionTrace, QueryRetrievalPlan
from app.services.knowledge_base.types_openai import SearchHit, SearchResponse

EARLY_STOP_TOP_SCORE = 0.88
MULTI_QUERY_SCORE_BONUS = 0.02
MAX_MULTI_QUERY_SCORE_BONUS = 0.06


@dataclass(frozen=True, slots=True)
class VectorRetrievalResult:
    hits: tuple[VectorHit, ...]
    top_score: float | None
    fallback_triggered: bool
    fallback_message: str | None


@dataclass(slots=True)
class _MergedHit:
    best_hit: SearchHit
    seen_count: int = 0


def execute_vector_retrieval(
    retriever,
    retrieval_plan: QueryRetrievalPlan,
    *,
    max_num_results: int | None = None,
    rewrite_query: bool = False,
    score_threshold: float | None = None,
    category: str | None = None,
    logical_id: str | None = None,
    attribute_filters=None,
    max_alternate_queries: int = 1,
) -> tuple[VectorRetrievalResult, QueryRetrievalExecutionTrace]:
    planned_queries = _planned_queries(
        retrieval_plan,
        max_alternate_queries=max_alternate_queries,
    )
    responses: list[SearchResponse] = []
    executed_queries: list[str] = []
    stop_reason: str | None = None

    for index, planned_query in enumerate(planned_queries):
        response = retriever.search(
            query=planned_query,
            max_num_results=max_num_results,
            rewrite_query=rewrite_query,
            score_threshold=score_threshold,
            category=category,
            logical_id=logical_id,
            attribute_filters=attribute_filters,
        )
        responses.append(response)
        executed_queries.append(planned_query)
        if index == 0 and len(planned_queries) > 1 and _should_stop_after_primary(response):
            stop_reason = "primary_top_score_sufficient"
            break

    if stop_reason is None:
        if len(planned_queries) == 1:
            stop_reason = "no_alternate_queries_planned"
        elif len(executed_queries) < len(planned_queries):
            stop_reason = "primary_top_score_sufficient"
        else:
            stop_reason = "planned_queries_exhausted"

    merged_response = _merge_search_responses(
        responses,
        max_num_results=max_num_results,
    )
    result = VectorRetrievalResult(
        hits=tuple(_vector_hit_from_search_hit(hit) for hit in merged_response.results),
        top_score=merged_response.top_score,
        fallback_triggered=merged_response.fallback_triggered,
        fallback_message=merged_response.fallback_message,
    )
    return (
        result,
        QueryRetrievalExecutionTrace(
            planned_queries=planned_queries,
            executed_queries=tuple(executed_queries),
            merged_raw_hit_count=sum(len(response.results) for response in responses),
            merged_result_count=len(result.hits),
            stop_reason=stop_reason,
        ),
    )


def _planned_queries(
    retrieval_plan: QueryRetrievalPlan,
    *,
    max_alternate_queries: int,
) -> tuple[str, ...]:
    alternates = retrieval_plan.alternate_queries[: max(0, max_alternate_queries)]
    return tuple(query for query in (retrieval_plan.primary_query, *alternates) if query)


def _should_stop_after_primary(response: SearchResponse) -> bool:
    return bool(response.results) and (response.top_score or 0.0) >= EARLY_STOP_TOP_SCORE


def _merge_search_responses(
    responses: list[SearchResponse],
    *,
    max_num_results: int | None,
) -> SearchResponse:
    if not responses:
        return SearchResponse(
            results=[],
            top_score=None,
            used_threshold=0.0,
            fallback_triggered=True,
            fallback_message=None,
        )

    merged: dict[tuple[str, str], _MergedHit] = {}
    for response in responses:
        for hit in response.results:
            key = (hit.file_id, _logical_id_for_hit(hit))
            record = merged.get(key)
            if record is None:
                merged[key] = _MergedHit(best_hit=hit, seen_count=1)
                continue
            record.seen_count += 1
            if hit.score > record.best_hit.score:
                record.best_hit = hit

    merged_hits = [
        SearchHit(
            file_id=record.best_hit.file_id,
            filename=record.best_hit.filename,
            score=min(
                1.0,
                record.best_hit.score
                + min(
                    MAX_MULTI_QUERY_SCORE_BONUS,
                    max(0, record.seen_count - 1) * MULTI_QUERY_SCORE_BONUS,
                ),
            ),
            attributes=record.best_hit.attributes,
            text=record.best_hit.text,
        )
        for record in merged.values()
    ]
    merged_hits.sort(
        key=lambda hit: (-hit.score, _logical_id_for_hit(hit), hit.filename.casefold())
    )
    if max_num_results is not None:
        merged_hits = merged_hits[:max_num_results]
    elif responses:
        merged_hits = merged_hits[: max(len(response.results) for response in responses)]

    fallback_message = next(
        (response.fallback_message for response in responses if response.fallback_message),
        None,
    )
    fallback_triggered = not merged_hits and any(
        response.fallback_triggered for response in responses
    )
    return SearchResponse(
        results=merged_hits,
        top_score=merged_hits[0].score if merged_hits else None,
        used_threshold=responses[0].used_threshold,
        fallback_triggered=fallback_triggered,
        fallback_message=fallback_message,
    )


def _logical_id_for_hit(hit: SearchHit) -> str:
    logical_id = str(hit.attributes.get("logical_id", "")).strip()
    return logical_id or hit.filename


def _vector_hit_from_search_hit(hit: SearchHit) -> VectorHit:
    logical_id = _logical_id_for_hit(hit)
    attributes = dict(hit.attributes)
    attributes["filename"] = hit.filename
    return VectorHit(
        section_id=f"{logical_id}:{hit.file_id}",
        file_id=hit.file_id,
        score=hit.score,
        text=hit.text,
        attributes=attributes,
    )
