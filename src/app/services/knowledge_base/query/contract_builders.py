from __future__ import annotations

from datetime import UTC, datetime

from app.services.knowledge_base.query.dto import NormalizedQuery, RewriteResult, RouterDecision
from app.services.knowledge_base.query.text import normalize_query_text
from app.services.knowledge_base.query.types import QueryRouteContext
from app.services.knowledge_base.retrieval.attributes import build_search_attributes
from app.services.knowledge_base.utils import dedupe_preserve_order


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


def build_router_decision(route_context: QueryRouteContext) -> RouterDecision:
    clarification_needed = (
        route_context.intent == "unknown"
        and route_context.strategy == "safe_fallback"
    )
    return RouterDecision(
        intent=route_context.intent,
        needs_clarification=clarification_needed,
        clarification_question=None,
        missing_slots=(),
        routing_flags={
            "scope": route_context.scope_detection.primary_scope,
            "scopes": route_context.scope_detection.scopes,
            "strategy": route_context.strategy,
            "needs_retrieval": route_context.needs_retrieval,
            "needs_structure": route_context.needs_structure,
            "policy_mode": route_context.policy_trace.mode,
            "intent_source": route_context.policy_trace.final_intent_source,
            "scope_source": route_context.policy_trace.final_scope_source,
            "strategy_source": route_context.policy_trace.final_strategy_source,
            "retrieval_source": route_context.policy_trace.final_retrieval_source,
        },
    )


def build_rewrite_result(
    normalized_query: NormalizedQuery,
    route_context: QueryRouteContext,
    *,
    category: str | None,
    logical_id: str | None,
    attribute_filters,
) -> RewriteResult:
    phrases = tuple(
        dedupe_preserve_order(
            [
                normalized_query.canonical_uk,
                route_context.retrieval_plan.primary_query,
                *route_context.retrieval_plan.alternate_queries,
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
        vector_query_uk=route_context.retrieval_plan.primary_query,
        lexical={
            "keywords": route_context.retrieval_plan.keywords,
            "synonyms": route_context.retrieval_plan.alternate_queries,
            "phrases": phrases,
        },
        filters={
            "category": category,
            "logical_id": logical_id,
            "language": "uk",
            "attribute_filters": merged_filters,
        },
    )
