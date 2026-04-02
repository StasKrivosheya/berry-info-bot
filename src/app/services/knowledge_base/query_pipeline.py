from __future__ import annotations

import logging

from app.services.knowledge_base.query_classifier import classify_query_intent
from app.services.knowledge_base.query_execution import execute_query_plan
from app.services.knowledge_base.query_planner import build_query_plan
from app.services.knowledge_base.query_scope import detect_query_scope
from app.services.knowledge_base.query_text import normalize_query_text
from app.services.knowledge_base.query_types import (
    QueryAnswerResult,
    QueryClassification,
    QueryPlan,
    QueryScopeDetection,
)
from app.services.knowledge_base.retrieval import KnowledgeBaseRetrievalService
from app.services.knowledge_base.structure_reader import KnowledgeBaseStructureReader

logger = logging.getLogger(__name__)

LOG_EVENT_PIPELINE_START = "kb_query_pipeline_start"
LOG_EVENT_PIPELINE_RUN = "kb_query_pipeline_run"


class KnowledgeBaseQueryPipeline:
    """Rules-first query interpretation pipeline built on top of raw retrieval."""

    def __init__(
        self,
        *,
        retriever: KnowledgeBaseRetrievalService | None = None,
        structure_reader: KnowledgeBaseStructureReader | None = None,
    ) -> None:
        self._retriever = retriever or KnowledgeBaseRetrievalService()
        self._structure_reader = structure_reader or KnowledgeBaseStructureReader()

    def classify_query(self, query: str) -> QueryClassification:
        return classify_query_intent(query)

    def detect_scope(self, query: str) -> QueryScopeDetection:
        return detect_query_scope(query)

    def plan_query(self, query: str) -> QueryPlan:
        classification = self.classify_query(query)
        scope_detection = self.detect_scope(query)
        return build_query_plan(classification, scope_detection)

    def answer_query(
        self,
        query: str,
        *,
        max_num_results: int | None = None,
        rewrite_query: bool = False,
        score_threshold: float | None = None,
        category: str | None = None,
        logical_id: str | None = None,
        attribute_filters=None,
    ) -> QueryAnswerResult:
        plan = self.plan_query(query)
        logger.debug(
            "%s query=%r normalized_query=%r intent=%s scope=%s strategy=%s",
            LOG_EVENT_PIPELINE_START,
            query,
            normalize_query_text(query),
            plan.intent,
            plan.scope_detection.primary_scope,
            plan.strategy,
        )
        search_response = None
        if plan.needs_retrieval:
            search_response = self._retriever.search(
                query=query,
                max_num_results=max_num_results,
                rewrite_query=rewrite_query,
                score_threshold=score_threshold,
                category=category,
                logical_id=logical_id,
                attribute_filters=attribute_filters,
            )

        result = execute_query_plan(
            query,
            plan,
            structure_reader=self._structure_reader,
            search_response=search_response,
        )
        logger.info(
            "%s intent=%s scope=%s strategy=%s fallback_used=%s",
            LOG_EVENT_PIPELINE_RUN,
            result.plan.intent,
            result.plan.scope_detection.primary_scope,
            result.plan.strategy,
            result.fallback_used,
        )
        return result
