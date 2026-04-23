from __future__ import annotations

import logging

from app.observability import emit_skipped_span, trace_stage
from app.services.knowledge_base.query.contract_builders import (
    build_normalized_query,
    build_rewrite_result,
    build_router_decision,
)
from app.services.knowledge_base.query.dto import AnswerResult, RewriteResult, RouterDecision
from app.services.knowledge_base.query.evidence import (
    EmptyLexicalRetriever,
    LexicalRetriever,
    build_evidence_packet,
)
from app.services.knowledge_base.query.execution import execute_query_answer
from app.services.knowledge_base.query.policy import KnowledgeBaseQueryPolicy
from app.services.knowledge_base.query.retrieval_execution import (
    VectorRetrievalResult,
    execute_vector_retrieval,
)
from app.services.knowledge_base.query.structure import KnowledgeBaseStructureReader
from app.services.knowledge_base.query.types import (
    QueryClassification,
    QueryInspectionResult,
    QueryLLMMode,
    QueryRetrievalExecutionTrace,
    QueryRouteContext,
    QueryScopeDetection,
)
from app.services.knowledge_base.retrieval.service import KnowledgeBaseRetrievalService

logger = logging.getLogger(__name__)

LOG_EVENT_PIPELINE_START = "kb_query_pipeline_start"
LOG_EVENT_PIPELINE_RUN = "kb_query_pipeline_run"
FALLBACK_MIN_TRUSTED_TOP_SCORE = 0.7


class KnowledgeBaseQueryPipeline:
    """DTO-first query pipeline with explicit routing, retrieval, evidence, and answer stages."""

    def __init__(
        self,
        *,
        retriever: KnowledgeBaseRetrievalService | None = None,
        structure_reader: KnowledgeBaseStructureReader | None = None,
        query_policy: KnowledgeBaseQueryPolicy | None = None,
        policy_settings=None,
        llm_interpreter=None,
        lexical_retriever: LexicalRetriever | None = None,
    ) -> None:
        self._retriever = retriever
        self._structure_reader = structure_reader or KnowledgeBaseStructureReader()
        self._query_policy = query_policy or KnowledgeBaseQueryPolicy(
            settings=policy_settings,
            llm_interpreter=llm_interpreter,
        )
        self._lexical_retriever = lexical_retriever or EmptyLexicalRetriever()

    def classify_query(self, query: str) -> QueryClassification:
        return self._query_policy.resolve_query_route(query).classification

    def detect_scope(self, query: str) -> QueryScopeDetection:
        return self._query_policy.resolve_query_route(query).scope_detection

    def plan_query(self, query: str) -> QueryRouteContext:
        return self._query_policy.resolve_query_route(query)

    def route_query(self, query: str) -> RouterDecision:
        return self.inspect_query(query).router_decision

    def rewrite_query(self, query: str) -> RewriteResult:
        return self.inspect_query(query).rewrite_result

    def inspect_query(
        self,
        query: str,
        *,
        max_num_results: int | None = None,
        rewrite_query: bool = False,
        score_threshold: float | None = None,
        category: str | None = None,
        logical_id: str | None = None,
        attribute_filters=None,
        user_locale: str = "uk-UA",
        detected_language: str = "uk",
    ) -> QueryInspectionResult:
        normalized_query = build_normalized_query(
            query,
            user_locale=user_locale,
            detected_language=detected_language,
        )
        runtime_mode = self._query_policy.settings.kb_query_llm_mode
        with trace_stage(
            "plan",
            meta={
                "phase": "initial",
                "runtime_mode": runtime_mode,
            },
        ):
            route_context = (
                self._query_policy.resolve_query_route(query)
                if runtime_mode == "forced"
                else self._resolve_initial_route(query)
            )
        logger.debug(
            (
                "%s query=%r normalized_query=%r intent=%s scope=%s strategy=%s "
                "mode=%s llm_used=%s"
            ),
            LOG_EVENT_PIPELINE_START,
            query,
            normalized_query.canonical_uk,
            route_context.intent,
            route_context.scope_detection.primary_scope,
            route_context.strategy,
            runtime_mode,
            route_context.policy_trace.llm_used,
        )

        if runtime_mode == "forced":
            inspection = self._run_route(
                query,
                normalized_query=normalized_query,
                route_context=route_context,
                max_num_results=max_num_results,
                rewrite_query=rewrite_query,
                score_threshold=score_threshold,
                category=category,
                logical_id=logical_id,
                attribute_filters=attribute_filters,
                max_alternate_queries=self._query_policy.settings.kb_query_llm_max_retrieval_variants,
            )
            self._log_pipeline_result(inspection)
            return inspection

        deterministic = self._run_route(
            query,
            normalized_query=normalized_query,
            route_context=route_context,
            max_num_results=max_num_results,
            rewrite_query=rewrite_query,
            score_threshold=score_threshold,
            category=category,
            logical_id=logical_id,
            attribute_filters=attribute_filters,
            max_alternate_queries=0,
        )
        escalation_reason = self._determine_escalation_reason(
            deterministic,
            mode=runtime_mode,
        )
        if escalation_reason is None:
            self._log_pipeline_result(deterministic)
            return deterministic

        with trace_stage(
            "plan",
            meta={
                "phase": "llm_escalation",
                "runtime_mode": runtime_mode,
            },
        ):
            llm_route_context = self._query_policy.resolve_query_route(
                query,
                llm_mode_override=runtime_mode,
            )

        final_inspection = deterministic
        retry_executed = False
        if self._should_retry_retrieval(route_context, llm_route_context):
            retry_executed = True
            final_inspection = self._run_route(
                query,
                normalized_query=normalized_query,
                route_context=llm_route_context,
                max_num_results=max_num_results,
                rewrite_query=rewrite_query,
                score_threshold=score_threshold,
                category=category,
                logical_id=logical_id,
                attribute_filters=attribute_filters,
                max_alternate_queries=0,
            )
        elif llm_route_context != route_context:
            final_inspection = self._rerender_with_existing_hits(
                query,
                normalized_query=normalized_query,
                route_context=llm_route_context,
                base=deterministic,
            )

        final_inspection = self._with_escalation_trace(
            deterministic,
            final_inspection,
            escalation_reason=escalation_reason,
            retry_executed=retry_executed,
        )
        self._log_pipeline_result(final_inspection)
        return final_inspection

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
        user_locale: str = "uk-UA",
        detected_language: str = "uk",
    ) -> AnswerResult:
        inspection = self.inspect_query(
            query,
            max_num_results=max_num_results,
            rewrite_query=rewrite_query,
            score_threshold=score_threshold,
            category=category,
            logical_id=logical_id,
            attribute_filters=attribute_filters,
            user_locale=user_locale,
            detected_language=detected_language,
        )
        return inspection.answer_result

    def _resolve_initial_route(self, query: str) -> QueryRouteContext:
        runtime_mode = self._query_policy.settings.kb_query_llm_mode
        if runtime_mode == "forced":
            return self._query_policy.resolve_query_route(query)
        return self._query_policy.resolve_query_route(
            query,
            llm_mode_override="disabled",
        )

    def _run_route(
        self,
        query: str,
        *,
        normalized_query,
        route_context: QueryRouteContext,
        max_num_results: int | None,
        rewrite_query: bool,
        score_threshold: float | None,
        category: str | None,
        logical_id: str | None,
        attribute_filters,
        max_alternate_queries: int,
    ) -> QueryInspectionResult:
        router_decision = build_router_decision(route_context)
        rewrite_result = build_rewrite_result(
            normalized_query,
            route_context,
            category=category,
            logical_id=logical_id,
            attribute_filters=attribute_filters,
        )
        stage_toggles = route_context.policy_trace.stage_toggles
        vector_result = VectorRetrievalResult(
            hits=(),
            top_score=None,
            fallback_triggered=False,
            fallback_message=None,
        )
        retrieval_trace = None
        if stage_toggles.retrieval_enabled and route_context.needs_retrieval:
            with trace_stage(
                "retrieval",
                meta=_stage_meta(
                    route_context,
                    phase="primary",
                    max_alternate_queries=max_alternate_queries,
                ),
            ):
                vector_result, retrieval_trace = execute_vector_retrieval(
                    self._get_retriever(),
                    route_context.retrieval_plan,
                    max_num_results=max_num_results,
                    rewrite_query=rewrite_query,
                    score_threshold=score_threshold,
                    category=category,
                    logical_id=logical_id,
                    attribute_filters=attribute_filters,
                    max_alternate_queries=max_alternate_queries,
                )
            retrieval_trace = QueryRetrievalExecutionTrace(
                initial_planned_queries=retrieval_trace.planned_queries,
                initial_executed_queries=retrieval_trace.executed_queries,
                initial_result_count=retrieval_trace.merged_result_count,
                initial_top_score=vector_result.top_score,
                initial_stop_reason=retrieval_trace.stop_reason,
                retry_executed=False,
                planned_queries=retrieval_trace.planned_queries,
                executed_queries=retrieval_trace.executed_queries,
                merged_raw_hit_count=retrieval_trace.merged_raw_hit_count,
                merged_result_count=retrieval_trace.merged_result_count,
                stop_reason=retrieval_trace.stop_reason,
            )
        elif route_context.needs_retrieval:
            emit_skipped_span(
                "retrieval",
                meta=_stage_meta(
                    route_context,
                    phase="primary",
                    reason="retrieval_disabled_by_configuration",
                ),
            )
            retrieval_trace = plan_retrieval_disabled_trace(route_context)
        else:
            emit_skipped_span(
                "retrieval",
                meta=_stage_meta(
                    route_context,
                    phase="primary",
                    reason="retrieval_not_required",
                ),
            )

        lexical_hits = ()
        if route_context.needs_retrieval:
            lexical_hits = self._lexical_retriever.search(
                query=rewrite_result.canonical_uk,
                max_results=max_num_results,
            )
        evidence_packet = build_evidence_packet(
            vector_hits=vector_result.hits,
            lexical_hits=lexical_hits,
        )

        if not stage_toggles.renderer_enabled:
            emit_skipped_span(
                "render",
                meta=_stage_meta(
                    route_context,
                    phase="primary",
                    reason="renderer_disabled_by_configuration",
                ),
            )
            answer_result = AnswerResult(
                state="fallback",
                answer_text="Renderer stage is disabled by configuration.",
                clarification_question=None,
                source_section_ids=(),
                debug_reason="renderer_disabled_by_configuration",
            )
        else:
            with trace_stage(
                "render",
                meta=_stage_meta(
                    route_context,
                    phase="primary",
                ),
            ):
                answer_result, retrieval_trace = execute_query_answer(
                    query,
                    route_context,
                    structure_reader=self._structure_reader,
                    vector_hits=vector_result.hits,
                    retrieval_trace=retrieval_trace,
                    fallback_message=vector_result.fallback_message,
                )

        return QueryInspectionResult(
            normalized_query=normalized_query,
            route_context=route_context,
            router_decision=router_decision,
            rewrite_result=rewrite_result,
            vector_hits=vector_result.hits,
            vector_top_score=vector_result.top_score,
            vector_fallback_message=vector_result.fallback_message,
            lexical_hits=lexical_hits,
            evidence_packet=evidence_packet,
            answer_result=answer_result,
            retrieval_trace=retrieval_trace,
        )

    def _rerender_with_existing_hits(
        self,
        query: str,
        *,
        normalized_query,
        route_context: QueryRouteContext,
        base: QueryInspectionResult,
    ) -> QueryInspectionResult:
        router_decision = build_router_decision(route_context)
        rewrite_result = build_rewrite_result(
            normalized_query,
            route_context,
            category=rewrite_result_category(base.rewrite_result),
            logical_id=rewrite_result_logical_id(base.rewrite_result),
            attribute_filters=base.rewrite_result.filters["attribute_filters"],
        )
        if not route_context.policy_trace.stage_toggles.renderer_enabled:
            emit_skipped_span(
                "render",
                meta=_stage_meta(
                    route_context,
                    phase="reuse_vector_hits",
                    reason="renderer_disabled_by_configuration",
                ),
            )
            answer_result = AnswerResult(
                state="fallback",
                answer_text="Renderer stage is disabled by configuration.",
                clarification_question=None,
                source_section_ids=(),
                debug_reason="renderer_disabled_by_configuration",
            )
            retrieval_trace = base.retrieval_trace
        else:
            with trace_stage(
                "render",
                meta=_stage_meta(
                    route_context,
                    phase="reuse_vector_hits",
                ),
            ):
                answer_result, retrieval_trace = execute_query_answer(
                    query,
                    route_context,
                    structure_reader=self._structure_reader,
                    vector_hits=base.vector_hits,
                    retrieval_trace=base.retrieval_trace,
                    fallback_message=base.vector_fallback_message,
                )

        return QueryInspectionResult(
            normalized_query=normalized_query,
            route_context=route_context,
            router_decision=router_decision,
            rewrite_result=rewrite_result,
            vector_hits=base.vector_hits,
            vector_top_score=base.vector_top_score,
            vector_fallback_message=base.vector_fallback_message,
            lexical_hits=base.lexical_hits,
            evidence_packet=base.evidence_packet,
            answer_result=answer_result,
            retrieval_trace=retrieval_trace,
        )

    def _determine_escalation_reason(
        self,
        inspection: QueryInspectionResult,
        *,
        mode: QueryLLMMode,
    ) -> str | None:
        if mode != "fallback":
            return None
        if not inspection.route_context.needs_retrieval:
            return None
        if not inspection.route_context.policy_trace.stage_toggles.retrieval_enabled:
            return None
        if not inspection.vector_hits:
            return "no_search_hits"
        if (
            inspection.vector_top_score is not None
            and inspection.vector_top_score < FALLBACK_MIN_TRUSTED_TOP_SCORE
        ):
            return "top_score_below_runtime_threshold"
        trace = inspection.retrieval_trace
        if trace is None:
            return "missing_retrieval_trace"
        if trace.renderer_trusted_top_hit is False:
            return trace.renderer_note or "renderer_low_confidence"
        return None

    def _should_retry_retrieval(
        self,
        initial_route: QueryRouteContext,
        llm_route: QueryRouteContext,
    ) -> bool:
        if not llm_route.needs_retrieval:
            return False
        return llm_route.retrieval_plan.primary_query != initial_route.retrieval_plan.primary_query

    def _with_escalation_trace(
        self,
        initial: QueryInspectionResult,
        final: QueryInspectionResult,
        *,
        escalation_reason: str,
        retry_executed: bool,
    ) -> QueryInspectionResult:
        initial_trace = initial.retrieval_trace
        final_trace = final.retrieval_trace
        if initial_trace is None and final_trace is None:
            return final

        combined_trace = QueryRetrievalExecutionTrace(
            initial_planned_queries=(
                initial_trace.initial_planned_queries if initial_trace is not None else ()
            ),
            initial_executed_queries=(
                initial_trace.initial_executed_queries if initial_trace is not None else ()
            ),
            initial_result_count=(
                initial_trace.initial_result_count if initial_trace is not None else 0
            ),
            initial_top_score=(
                initial_trace.initial_top_score if initial_trace is not None else None
            ),
            initial_stop_reason=(
                initial_trace.initial_stop_reason if initial_trace is not None else None
            ),
            llm_escalation_triggered=True,
            llm_escalation_reason=escalation_reason,
            retry_executed=retry_executed,
            planned_queries=final_trace.planned_queries if final_trace is not None else (),
            executed_queries=final_trace.executed_queries if final_trace is not None else (),
            retry_result_count=(
                final_trace.merged_result_count
                if retry_executed and final_trace is not None
                else 0
            ),
            retry_top_score=(
                final.vector_top_score
                if retry_executed and final_trace is not None
                else None
            ),
            merged_raw_hit_count=final_trace.merged_raw_hit_count if final_trace is not None else 0,
            merged_result_count=final_trace.merged_result_count if final_trace is not None else 0,
            stop_reason=final_trace.stop_reason if final_trace is not None else None,
            renderer_trusted_top_hit=(
                final_trace.renderer_trusted_top_hit if final_trace is not None else None
            ),
            renderer_note=final_trace.renderer_note if final_trace is not None else None,
        )
        return QueryInspectionResult(
            normalized_query=final.normalized_query,
            route_context=final.route_context,
            router_decision=final.router_decision,
            rewrite_result=final.rewrite_result,
            vector_hits=final.vector_hits,
            vector_top_score=final.vector_top_score,
            vector_fallback_message=final.vector_fallback_message,
            lexical_hits=final.lexical_hits,
            evidence_packet=final.evidence_packet,
            answer_result=final.answer_result,
            retrieval_trace=combined_trace,
        )

    def _log_pipeline_result(self, inspection: QueryInspectionResult) -> None:
        logger.info(
            "%s intent=%s scope=%s strategy=%s answer_state=%s",
            LOG_EVENT_PIPELINE_RUN,
            inspection.route_context.intent,
            inspection.route_context.scope_detection.primary_scope,
            inspection.route_context.strategy,
            inspection.answer_result.state,
        )

    def _get_retriever(self) -> KnowledgeBaseRetrievalService:
        if self._retriever is None:
            self._retriever = KnowledgeBaseRetrievalService()
        return self._retriever


def plan_retrieval_disabled_trace(route_context: QueryRouteContext) -> QueryRetrievalExecutionTrace:
    return QueryRetrievalExecutionTrace(
        initial_planned_queries=route_context.retrieval_plan.planned_queries,
        initial_executed_queries=(),
        initial_result_count=0,
        initial_top_score=None,
        initial_stop_reason="retrieval_disabled_by_configuration",
        retry_executed=False,
        planned_queries=route_context.retrieval_plan.planned_queries,
        executed_queries=(),
        merged_raw_hit_count=0,
        merged_result_count=0,
        stop_reason="retrieval_disabled_by_configuration",
    )


def _stage_meta(
    route_context: QueryRouteContext,
    *,
    phase: str,
    reason: str | None = None,
    max_alternate_queries: int | None = None,
) -> dict[str, object]:
    meta: dict[str, object] = {
        "phase": phase,
        "intent": route_context.intent,
        "scope": route_context.scope_detection.primary_scope,
        "strategy": route_context.strategy,
        "retrieval_source": route_context.retrieval_plan.source,
    }
    if max_alternate_queries is not None:
        meta["max_alternate_queries"] = max_alternate_queries
    if reason is not None:
        meta["reason"] = reason
    return meta


def rewrite_result_category(rewrite_result: RewriteResult) -> str | None:
    return rewrite_result.filters["category"]


def rewrite_result_logical_id(rewrite_result: RewriteResult) -> str | None:
    return rewrite_result.filters["logical_id"]
