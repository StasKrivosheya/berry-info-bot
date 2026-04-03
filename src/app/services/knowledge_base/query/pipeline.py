from __future__ import annotations

import logging

from app.services.knowledge_base.query.execution import execute_query_plan
from app.services.knowledge_base.query.policy import KnowledgeBaseQueryPolicy
from app.services.knowledge_base.query.retrieval_execution import execute_retrieval_plan
from app.services.knowledge_base.query.structure import KnowledgeBaseStructureReader
from app.services.knowledge_base.query.text import normalize_query_text
from app.services.knowledge_base.query.types import (
    QueryAnswerResult,
    QueryClassification,
    QueryPlan,
    QueryScopeDetection,
)
from app.services.knowledge_base.retrieval.service import KnowledgeBaseRetrievalService

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
        query_policy: KnowledgeBaseQueryPolicy | None = None,
        policy_settings=None,
        llm_interpreter=None,
    ) -> None:
        self._retriever = retriever
        self._structure_reader = structure_reader or KnowledgeBaseStructureReader()
        self._query_policy = query_policy or KnowledgeBaseQueryPolicy(
            settings=policy_settings,
            llm_interpreter=llm_interpreter,
        )

    def classify_query(self, query: str) -> QueryClassification:
        return self.plan_query(query).classification

    def detect_scope(self, query: str) -> QueryScopeDetection:
        return self.plan_query(query).scope_detection

    def plan_query(self, query: str) -> QueryPlan:
        return self._query_policy.resolve_query_plan(query)

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
            (
                "%s query=%r normalized_query=%r intent=%s scope=%s strategy=%s "
                "mode=%s llm_used=%s"
            ),
            LOG_EVENT_PIPELINE_START,
            query,
            normalize_query_text(query),
            plan.intent,
            plan.scope_detection.primary_scope,
            plan.strategy,
            plan.policy_trace.mode,
            plan.policy_trace.llm_used,
        )
        stage_toggles = plan.policy_trace.stage_toggles
        search_response = None
        retrieval_trace = None
        if stage_toggles.retrieval_enabled and plan.needs_retrieval:
            search_response, retrieval_trace = execute_retrieval_plan(
                self._get_retriever(),
                plan.retrieval_plan,
                max_num_results=max_num_results,
                rewrite_query=rewrite_query,
                score_threshold=score_threshold,
                category=category,
                logical_id=logical_id,
                attribute_filters=attribute_filters,
                max_alternate_queries=self._query_policy.settings.kb_query_llm_max_retrieval_variants,
            )
        elif plan.needs_retrieval:
            retrieval_trace = plan_retrieval_disabled_trace(plan)

        if not stage_toggles.renderer_enabled:
            result = QueryAnswerResult(
                plan=plan,
                summary="Renderer stage is disabled by configuration.",
                blocks=(),
                sources=(),
                search_response=search_response,
                fallback_used=True,
                retrieval_trace=retrieval_trace,
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

        result = execute_query_plan(
            query,
            plan,
            structure_reader=self._structure_reader,
            search_response=search_response,
            retrieval_trace=retrieval_trace,
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

    def _get_retriever(self) -> KnowledgeBaseRetrievalService:
        if self._retriever is None:
            self._retriever = KnowledgeBaseRetrievalService()
        return self._retriever


def plan_retrieval_disabled_trace(plan: QueryPlan):
    from app.services.knowledge_base.query.types import QueryRetrievalExecutionTrace

    return QueryRetrievalExecutionTrace(
        planned_queries=plan.retrieval_plan.planned_queries,
        executed_queries=(),
        merged_raw_hit_count=0,
        merged_result_count=0,
        stop_reason="retrieval_disabled_by_configuration",
    )
