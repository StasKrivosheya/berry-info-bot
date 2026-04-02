from __future__ import annotations

import logging

from app.services.knowledge_base.query_types import (
    QueryClassification,
    QueryPlan,
    QueryScopeDetection,
)

logger = logging.getLogger(__name__)

LOG_EVENT_QUERY_PLANNED = "kb_query_planned"


def build_query_plan(
    classification: QueryClassification,
    scope_detection: QueryScopeDetection,
) -> QueryPlan:
    if classification.intent == "enumeration":
        plan = QueryPlan(
            classification=classification,
            scope_detection=scope_detection,
            strategy="enumeration_catalog",
            needs_retrieval=False,
            needs_structure=True,
            rationale=(
                "Enumeration intent selects catalog/list strategy.",
                (
                    "Vector retrieval is optional and skipped for deterministic "
                    "structure-first listing."
                ),
            ),
        )
    elif classification.intent == "overview":
        plan = QueryPlan(
            classification=classification,
            scope_detection=scope_detection,
            strategy="overview_summary",
            needs_retrieval=False,
            needs_structure=True,
            rationale=(
                "Overview intent selects grouped summary strategy.",
                "Vector retrieval is skipped so broad answers do not depend on top-k chunks.",
            ),
        )
    elif classification.intent == "comparison":
        plan = QueryPlan(
            classification=classification,
            scope_detection=scope_detection,
            strategy="comparison_summary",
            needs_retrieval=True,
            needs_structure=True,
            rationale=(
                "Comparison intent needs retrieval to find candidate items.",
                "Structure is used to render candidate items comparatively.",
            ),
        )
    elif classification.intent == "detail":
        plan = QueryPlan(
            classification=classification,
            scope_detection=scope_detection,
            strategy="detail_retrieval",
            needs_retrieval=True,
            needs_structure=True,
            rationale=(
                "Detail intent selects retrieval-backed section answering.",
                "Structure is used to turn raw hits into coherent sections.",
            ),
        )
    else:
        plan = QueryPlan(
            classification=classification,
            scope_detection=scope_detection,
            strategy="safe_fallback",
            needs_retrieval=True,
            needs_structure=True,
            rationale=(
                "Unknown intent selects safe fallback.",
                (
                    "Retrieval may still provide nearby sections, but the pipeline "
                    "will degrade gracefully."
                ),
            ),
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
