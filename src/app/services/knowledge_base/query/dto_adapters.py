from __future__ import annotations

from datetime import UTC, datetime

from app.services.knowledge_base.normalizer import slugify
from app.services.knowledge_base.query.dto import (
    AnswerResult,
    EvidenceItem,
    EvidencePacket,
    LexicalHit,
    NormalizedQuery,
    RewriteResult,
    RouterDecision,
    VectorHit,
)
from app.services.knowledge_base.query.renderer import render_query_answer
from app.services.knowledge_base.query.structure import KnowledgeBaseStructureReader
from app.services.knowledge_base.query.text import normalize_query_text
from app.services.knowledge_base.query.types import QueryAnswerResult, QueryPlan
from app.services.knowledge_base.retrieval.attributes import build_search_attributes
from app.services.knowledge_base.utils import dedupe_preserve_order, search_hit_logical_id


def build_normalized_query(
    raw_text: str,
    *,
    user_locale: str = "uk-UA",
    detected_language: str = "uk",
    created_at: datetime | None = None,
) -> NormalizedQuery:
    return NormalizedQuery(
        raw_text=raw_text,
        user_locale=user_locale,
        detected_language=detected_language,
        canonical_uk=normalize_query_text(raw_text),
        created_at=created_at or datetime.now(tz=UTC),
    )


def router_decision_from_plan(plan: QueryPlan) -> RouterDecision:
    clarification_needed = plan.intent == "unknown" and plan.strategy == "safe_fallback"
    return RouterDecision(
        intent=plan.intent,
        needs_clarification=clarification_needed,
        clarification_question=None,
        missing_slots=(),
        routing_flags={
            "scope": plan.scope_detection.primary_scope,
            "scopes": plan.scope_detection.scopes,
            "strategy": plan.strategy,
            "needs_retrieval": plan.needs_retrieval,
            "needs_structure": plan.needs_structure,
            "policy_mode": plan.policy_trace.mode,
            "intent_source": plan.policy_trace.final_intent_source,
            "scope_source": plan.policy_trace.final_scope_source,
            "strategy_source": plan.policy_trace.final_strategy_source,
            "retrieval_source": plan.policy_trace.final_retrieval_source,
        },
    )


def rewrite_result_from_plan(
    normalized_query: NormalizedQuery,
    plan: QueryPlan,
    *,
    category: str | None,
    logical_id: str | None,
    attribute_filters,
) -> RewriteResult:
    phrases = tuple(
        dedupe_preserve_order(
            [
                normalized_query.canonical_uk,
                plan.retrieval_plan.primary_query,
                *plan.retrieval_plan.alternate_queries,
            ]
        )
    )
    merged_filters = build_search_attributes(
        attribute_filters=attribute_filters,
        category=category,
        logical_id=logical_id,
        language="uk",
    )
    return RewriteResult(
        canonical_uk=normalized_query.canonical_uk,
        vector_query_uk=plan.retrieval_plan.primary_query,
        lexical={
            "keywords": plan.retrieval_plan.keywords,
            "synonyms": plan.retrieval_plan.alternate_queries,
            "phrases": phrases,
        },
        filters={
            "category": category,
            "logical_id": logical_id,
            "language": "uk",
            "attribute_filters": merged_filters,
        },
    )


def vector_hits_from_search_response(
    search_response,
    *,
    structure_reader: KnowledgeBaseStructureReader,
) -> tuple[VectorHit, ...]:
    if search_response is None:
        return ()

    hits: list[VectorHit] = []
    for hit in search_response.results:
        hit_context = structure_reader.resolve_hit_context(hit)
        logical_id = search_hit_logical_id(hit)
        heading_path = hit_context.heading_path if hit_context is not None else ()
        attributes = dict(hit.attributes)
        if heading_path:
            attributes["heading_path"] = " > ".join(heading_path)
        section_id = _section_id(logical_id, heading_path, file_id=hit.file_id)
        hits.append(
            VectorHit(
                section_id=section_id,
                file_id=hit.file_id,
                score=hit.score,
                text=hit.text,
                attributes=attributes,
            )
        )
    return tuple(hits)


def lexical_hits_stub() -> tuple[LexicalHit, ...]:
    return ()


def build_evidence_packet(
    *,
    vector_hits: tuple[VectorHit, ...],
    lexical_hits: tuple[LexicalHit, ...],
    token_budget: int | None = None,
) -> EvidencePacket:
    remaining_budget = token_budget
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
        if remaining_budget is not None and token_budget_used + item_tokens > remaining_budget:
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
            if remaining_budget is not None and token_budget_used + item_tokens > remaining_budget:
                truncation_applied = True
                break
            items.append(item)
            token_budget_used += item_tokens

    return EvidencePacket(
        items=tuple(items),
        token_budget_used=token_budget_used,
        truncation_applied=truncation_applied,
    )


def answer_result_from_query_answer_result(
    result: QueryAnswerResult,
    *,
    evidence_packet: EvidencePacket,
    router_decision: RouterDecision,
) -> AnswerResult:
    if router_decision.needs_clarification and router_decision.clarification_question:
        state = "clarification"
    elif result.fallback_used:
        state = "fallback"
    else:
        state = "answered"

    source_section_ids = tuple(
        dedupe_preserve_order(
            [item.section_id for item in evidence_packet.items]
            or list(result.sources)
        )
    )
    debug_reason = None
    if result.retrieval_trace is not None and result.retrieval_trace.renderer_note:
        debug_reason = result.retrieval_trace.renderer_note
    elif result.plan.policy_trace.llm_failure_reason:
        debug_reason = result.plan.policy_trace.llm_failure_reason
    elif result.fallback_used:
        debug_reason = "fallback_used"

    return AnswerResult(
        state=state,
        answer_text=render_query_answer(result),
        clarification_question=router_decision.clarification_question,
        source_section_ids=source_section_ids,
        debug_reason=debug_reason,
    )


def _section_id(logical_id: str, heading_path: tuple[str, ...], *, file_id: str) -> str:
    if heading_path:
        return f"{logical_id}:{slugify(' '.join(heading_path))}"
    return f"{logical_id}:{file_id}"


def _token_count(text: str) -> int:
    return len([token for token in text.split() if token])
