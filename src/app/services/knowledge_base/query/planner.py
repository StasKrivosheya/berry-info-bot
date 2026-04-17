from __future__ import annotations

import logging

from app.services.knowledge_base.query.types import (
    QueryClassification,
    QueryRetrievalPlan,
    QueryRouteContext,
    QueryScopeDetection,
    QueryStrategy,
)

logger = logging.getLogger(__name__)

LOG_EVENT_QUERY_PLANNED = "kb_query_planned"
STRATEGY_FOR_INTENT: dict[str, QueryStrategy] = {
    "enumeration": "enumeration_catalog",
    "overview": "overview_summary",
    "comparison": "comparison_summary",
    "detail": "detail_retrieval",
    "unknown": "safe_fallback",
}
STRATEGY_RATIONALES: dict[QueryStrategy, tuple[str, ...]] = {
    "enumeration_catalog": (
        "Enumeration intent selects catalog/list strategy.",
        "Vector retrieval is optional and skipped for deterministic structure-first listing.",
    ),
    "overview_summary": (
        "Overview intent selects grouped summary strategy.",
        "Vector retrieval is skipped so broad answers do not depend on top-k chunks.",
    ),
    "comparison_summary": (
        "Comparison intent needs retrieval to find candidate items.",
        "Structure is used to render candidate items comparatively.",
    ),
    "detail_retrieval": (
        "Detail intent selects retrieval-backed section answering.",
        "Structure is used to turn raw hits into coherent sections.",
    ),
    "safe_fallback": (
        "Unknown intent selects safe fallback.",
        "Retrieval may still provide nearby sections, but the pipeline will degrade gracefully.",
    ),
}
STRATEGY_REQUIREMENTS: dict[QueryStrategy, tuple[bool, bool]] = {
    "enumeration_catalog": (False, True),
    "overview_summary": (False, True),
    "comparison_summary": (True, True),
    "detail_retrieval": (True, True),
    "safe_fallback": (True, True),
}


def build_query_plan(
    classification: QueryClassification,
    scope_detection: QueryScopeDetection,
    retrieval_plan: QueryRetrievalPlan,
) -> QueryRouteContext:
    strategy = strategy_for_intent(classification.intent)
    plan = build_query_plan_with_strategy(
        classification,
        scope_detection,
        retrieval_plan,
        strategy,
        rationale=STRATEGY_RATIONALES[strategy],
    )
    logger.info(
        "%s intent=%s scope=%s strategy=%s needs_retrieval=%s needs_structure=%s",
        LOG_EVENT_QUERY_PLANNED,
        plan.intent,
        plan.scope_detection.primary_scope,
        plan.strategy,
        plan.needs_retrieval,
        plan.needs_structure,
    )
    return plan


def build_query_plan_with_strategy(
    classification: QueryClassification,
    scope_detection: QueryScopeDetection,
    retrieval_plan: QueryRetrievalPlan,
    strategy: QueryStrategy,
    *,
    rationale: tuple[str, ...] | None = None,
) -> QueryRouteContext:
    needs_retrieval, needs_structure = strategy_requirements(strategy)
    return QueryRouteContext(
        classification=classification,
        scope_detection=scope_detection,
        strategy=strategy,
        retrieval_plan=retrieval_plan,
        needs_retrieval=needs_retrieval,
        needs_structure=needs_structure,
        rationale=rationale or STRATEGY_RATIONALES[strategy],
    )


def strategy_for_intent(intent: str) -> QueryStrategy:
    return STRATEGY_FOR_INTENT.get(intent, "safe_fallback")


def strategy_requirements(strategy: QueryStrategy) -> tuple[bool, bool]:
    return STRATEGY_REQUIREMENTS[strategy]


def strategy_matches_intent(intent: str, strategy: QueryStrategy) -> bool:
    return strategy == "safe_fallback" or strategy == strategy_for_intent(intent)
