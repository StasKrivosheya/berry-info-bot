from __future__ import annotations

import logging
from dataclasses import dataclass

from app.observability import emit_skipped_span, trace_stage
from app.services.knowledge_base.query.dto import (
    AnswerResult,
    EvidencePacket,
    LexicalHit,
    NormalizedQuery,
    RewriteResult,
    RouterDecision,
    VectorHit,
)
from app.services.knowledge_base.query.dto_adapters import (
    answer_result_from_query_answer_result,
    build_evidence_packet,
    build_normalized_query,
    lexical_hits_stub,
    rewrite_result_from_plan,
    router_decision_from_plan,
    vector_hits_from_search_response,
)
from app.services.knowledge_base.query.execution import execute_query_plan
from app.services.knowledge_base.query.policy import KnowledgeBaseQueryPolicy
from app.services.knowledge_base.query.retrieval_execution import execute_retrieval_plan
from app.services.knowledge_base.query.structure import KnowledgeBaseStructureReader
from app.services.knowledge_base.query.text import normalize_query_text
from app.services.knowledge_base.query.types import (
    QueryAnswerResult,
    QueryClassification,
    QueryLLMMode,
    QueryPlan,
    QueryRetrievalExecutionTrace,
    QueryScopeDetection,
)
from app.services.knowledge_base.retrieval.service import KnowledgeBaseRetrievalService

logger = logging.getLogger(__name__)

LOG_EVENT_PIPELINE_START = "kb_query_pipeline_start"
LOG_EVENT_PIPELINE_RUN = "kb_query_pipeline_run"
FALLBACK_MIN_TRUSTED_TOP_SCORE = 0.7


@dataclass(frozen=True, slots=True)
class _PipelineContractRun:
    normalized_query: NormalizedQuery
    router_decision: RouterDecision
    rewrite_result: RewriteResult
    vector_hits: tuple[VectorHit, ...]
    lexical_hits: tuple[LexicalHit, ...]
    evidence_packet: EvidencePacket
    answer_result: AnswerResult
    legacy_result: QueryAnswerResult


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
        return self._query_policy.resolve_query_plan(query).classification

    def detect_scope(self, query: str) -> QueryScopeDetection:
        return self._query_policy.resolve_query_plan(query).scope_detection

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
        return self._execute_pipeline_contracts(
            query,
            max_num_results=max_num_results,
            rewrite_query=rewrite_query,
            score_threshold=score_threshold,
            category=category,
            logical_id=logical_id,
            attribute_filters=attribute_filters,
        ).legacy_result

    def answer_query_dto(
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
        return self._execute_pipeline_contracts(
            query,
            max_num_results=max_num_results,
            rewrite_query=rewrite_query,
            score_threshold=score_threshold,
            category=category,
            logical_id=logical_id,
            attribute_filters=attribute_filters,
            user_locale=user_locale,
            detected_language=detected_language,
        ).answer_result

    def _execute_pipeline_contracts(
        self,
        query: str,
        *,
        max_num_results: int | None,
        rewrite_query: bool,
        score_threshold: float | None,
        category: str | None,
        logical_id: str | None,
        attribute_filters,
        user_locale: str = "uk-UA",
        detected_language: str = "uk",
    ) -> _PipelineContractRun:
        normalized_query = build_normalized_query(
            query,
            user_locale=user_locale,
            detected_language=detected_language,
        )
        legacy_result = self._execute_legacy_answer_query(
            query,
            max_num_results=max_num_results,
            rewrite_query=rewrite_query,
            score_threshold=score_threshold,
            category=category,
            logical_id=logical_id,
            attribute_filters=attribute_filters,
        )
        router_decision = router_decision_from_plan(legacy_result.plan)
        rewrite_result = rewrite_result_from_plan(
            normalized_query,
            legacy_result.plan,
            category=category,
            logical_id=logical_id,
            attribute_filters=attribute_filters,
        )
        vector_hits = vector_hits_from_search_response(
            legacy_result.search_response,
            structure_reader=self._structure_reader,
        )
        lexical_hits = lexical_hits_stub()
        evidence_packet = build_evidence_packet(
            vector_hits=vector_hits,
            lexical_hits=lexical_hits,
        )
        answer_result = answer_result_from_query_answer_result(
            legacy_result,
            evidence_packet=evidence_packet,
            router_decision=router_decision,
        )
        return _PipelineContractRun(
            normalized_query=normalized_query,
            router_decision=router_decision,
            rewrite_result=rewrite_result,
            vector_hits=vector_hits,
            lexical_hits=lexical_hits,
            evidence_packet=evidence_packet,
            answer_result=answer_result,
            legacy_result=legacy_result,
        )

    def _execute_legacy_answer_query(
        self,
        query: str,
        *,
        max_num_results: int | None,
        rewrite_query: bool,
        score_threshold: float | None,
        category: str | None,
        logical_id: str | None,
        attribute_filters,
    ) -> QueryAnswerResult:
        runtime_mode = self._query_policy.settings.kb_query_llm_mode
        with trace_stage(
            "plan",
            meta={
                "phase": "initial",
                "runtime_mode": runtime_mode,
            },
        ):
            plan = (
                self._query_policy.resolve_query_plan(query)
                if runtime_mode == "forced"
                else self._resolve_initial_plan(query)
            )
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
            runtime_mode,
            plan.policy_trace.llm_used,
        )

        if runtime_mode == "forced":
            result = self._run_plan(
                query,
                plan,
                max_num_results=max_num_results,
                rewrite_query=rewrite_query,
                score_threshold=score_threshold,
                category=category,
                logical_id=logical_id,
                attribute_filters=attribute_filters,
                max_alternate_queries=self._query_policy.settings.kb_query_llm_max_retrieval_variants,
            )
            self._log_pipeline_result(result)
            return result

        deterministic_result = self._run_plan(
            query,
            plan,
            max_num_results=max_num_results,
            rewrite_query=rewrite_query,
            score_threshold=score_threshold,
            category=category,
            logical_id=logical_id,
            attribute_filters=attribute_filters,
            max_alternate_queries=0,
        )
        escalation_reason = self._determine_escalation_reason(
            deterministic_result,
            mode=runtime_mode,
        )
        if escalation_reason is None:
            self._log_pipeline_result(deterministic_result)
            return deterministic_result

        with trace_stage(
            "plan",
            meta={
                "phase": "llm_escalation",
                "runtime_mode": runtime_mode,
            },
        ):
            llm_plan = self._query_policy.resolve_query_plan(
                query,
                llm_mode_override=runtime_mode,
            )
        final_result = deterministic_result
        retry_result: QueryAnswerResult | None = None
        if self._should_retry_retrieval(plan, llm_plan):
            retry_result = self._run_plan(
                query,
                llm_plan,
                max_num_results=max_num_results,
                rewrite_query=rewrite_query,
                score_threshold=score_threshold,
                category=category,
                logical_id=logical_id,
                attribute_filters=attribute_filters,
                max_alternate_queries=0,
            )
            final_result = retry_result
        elif llm_plan != plan:
            final_result = self._render_with_existing_search_response(
                query,
                llm_plan,
                deterministic_result,
            )

        final_result = self._with_escalation_trace(
            deterministic_result,
            final_result,
            escalation_reason=escalation_reason,
            retry_executed=retry_result is not None,
        )
        self._log_pipeline_result(final_result)
        return final_result

    def _resolve_initial_plan(self, query: str) -> QueryPlan:
        runtime_mode = self._query_policy.settings.kb_query_llm_mode
        if runtime_mode == "forced":
            return self._query_policy.resolve_query_plan(query)
        return self._query_policy.resolve_query_plan(
            query,
            llm_mode_override="disabled",
        )

    def _run_plan(
        self,
        query: str,
        plan: QueryPlan,
        *,
        max_num_results: int | None,
        rewrite_query: bool,
        score_threshold: float | None,
        category: str | None,
        logical_id: str | None,
        attribute_filters,
        max_alternate_queries: int,
    ) -> QueryAnswerResult:
        stage_toggles = plan.policy_trace.stage_toggles
        search_response = None
        retrieval_trace = None
        if stage_toggles.retrieval_enabled and plan.needs_retrieval:
            with trace_stage(
                "retrieval",
                meta=_stage_meta(
                    plan,
                    phase="primary",
                    max_alternate_queries=max_alternate_queries,
                ),
            ):
                search_response, retrieval_trace = execute_retrieval_plan(
                    self._get_retriever(),
                    plan.retrieval_plan,
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
                initial_top_score=search_response.top_score,
                initial_stop_reason=retrieval_trace.stop_reason,
                retry_executed=False,
                planned_queries=retrieval_trace.planned_queries,
                executed_queries=retrieval_trace.executed_queries,
                merged_raw_hit_count=retrieval_trace.merged_raw_hit_count,
                merged_result_count=retrieval_trace.merged_result_count,
                stop_reason=retrieval_trace.stop_reason,
            )
        elif plan.needs_retrieval:
            emit_skipped_span(
                "retrieval",
                meta=_stage_meta(
                    plan,
                    phase="primary",
                    reason="retrieval_disabled_by_configuration",
                ),
            )
            retrieval_trace = plan_retrieval_disabled_trace(plan)
        else:
            emit_skipped_span(
                "retrieval",
                meta=_stage_meta(
                    plan,
                    phase="primary",
                    reason="retrieval_not_required",
                ),
            )

        if not stage_toggles.renderer_enabled:
            emit_skipped_span(
                "render",
                meta=_stage_meta(
                    plan,
                    phase="primary",
                    reason="renderer_disabled_by_configuration",
                ),
            )
            return QueryAnswerResult(
                plan=plan,
                summary="Renderer stage is disabled by configuration.",
                blocks=(),
                sources=(),
                search_response=search_response,
                fallback_used=True,
                retrieval_trace=retrieval_trace,
            )

        with trace_stage(
            "render",
            meta=_stage_meta(
                plan,
                phase="primary",
            ),
        ):
            return execute_query_plan(
                query,
                plan,
                structure_reader=self._structure_reader,
                search_response=search_response,
                retrieval_trace=retrieval_trace,
            )

    def _render_with_existing_search_response(
        self,
        query: str,
        plan: QueryPlan,
        base_result: QueryAnswerResult,
    ) -> QueryAnswerResult:
        if not plan.policy_trace.stage_toggles.renderer_enabled:
            emit_skipped_span(
                "render",
                meta=_stage_meta(
                    plan,
                    phase="reuse_search_response",
                    reason="renderer_disabled_by_configuration",
                ),
            )
            return QueryAnswerResult(
                plan=plan,
                summary="Renderer stage is disabled by configuration.",
                blocks=(),
                sources=(),
                search_response=base_result.search_response,
                fallback_used=True,
                retrieval_trace=base_result.retrieval_trace,
            )
        with trace_stage(
            "render",
            meta=_stage_meta(
                plan,
                phase="reuse_search_response",
            ),
        ):
            return execute_query_plan(
                query,
                plan,
                structure_reader=self._structure_reader,
                search_response=base_result.search_response,
                retrieval_trace=base_result.retrieval_trace,
            )

    def _determine_escalation_reason(
        self,
        result: QueryAnswerResult,
        *,
        mode: QueryLLMMode,
    ) -> str | None:
        if mode != "fallback":
            return None
        if not result.plan.needs_retrieval:
            return None
        if not result.plan.policy_trace.stage_toggles.retrieval_enabled:
            return None
        if result.search_response is None or not result.search_response.results:
            return "no_search_hits"
        if (
            result.search_response.top_score is not None
            and result.search_response.top_score < FALLBACK_MIN_TRUSTED_TOP_SCORE
        ):
            return "top_score_below_runtime_threshold"
        trace = result.retrieval_trace
        if trace is None:
            return "missing_retrieval_trace"
        if trace.renderer_trusted_top_hit is False:
            return trace.renderer_note or "renderer_low_confidence"
        return None

    def _should_retry_retrieval(
        self,
        initial_plan: QueryPlan,
        llm_plan: QueryPlan,
    ) -> bool:
        if not llm_plan.needs_retrieval:
            return False
        return llm_plan.retrieval_plan.primary_query != initial_plan.retrieval_plan.primary_query

    def _with_escalation_trace(
        self,
        initial_result: QueryAnswerResult,
        final_result: QueryAnswerResult,
        *,
        escalation_reason: str,
        retry_executed: bool,
    ) -> QueryAnswerResult:
        initial_trace = initial_result.retrieval_trace
        final_trace = final_result.retrieval_trace
        if initial_trace is None and final_trace is None:
            return final_result

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
                final_result.search_response.top_score
                if (
                    retry_executed
                    and final_trace is not None
                    and final_result.search_response is not None
                )
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
        return QueryAnswerResult(
            plan=final_result.plan,
            blocks=final_result.blocks,
            summary=final_result.summary,
            sources=final_result.sources,
            search_response=final_result.search_response,
            fallback_used=final_result.fallback_used,
            retrieval_trace=combined_trace,
        )

    def _log_pipeline_result(self, result: QueryAnswerResult) -> None:
        logger.info(
            "%s intent=%s scope=%s strategy=%s fallback_used=%s",
            LOG_EVENT_PIPELINE_RUN,
            result.plan.intent,
            result.plan.scope_detection.primary_scope,
            result.plan.strategy,
            result.fallback_used,
        )

    def _get_retriever(self) -> KnowledgeBaseRetrievalService:
        if self._retriever is None:
            self._retriever = KnowledgeBaseRetrievalService()
        return self._retriever


def plan_retrieval_disabled_trace(plan: QueryPlan) -> QueryRetrievalExecutionTrace:
    return QueryRetrievalExecutionTrace(
        initial_planned_queries=plan.retrieval_plan.planned_queries,
        initial_executed_queries=(),
        initial_result_count=0,
        initial_top_score=None,
        initial_stop_reason="retrieval_disabled_by_configuration",
        retry_executed=False,
        planned_queries=plan.retrieval_plan.planned_queries,
        executed_queries=(),
        merged_raw_hit_count=0,
        merged_result_count=0,
        stop_reason="retrieval_disabled_by_configuration",
    )


def _stage_meta(
    plan: QueryPlan,
    *,
    phase: str,
    reason: str | None = None,
    max_alternate_queries: int | None = None,
) -> dict[str, object]:
    meta: dict[str, object] = {
        "phase": phase,
        "intent": plan.intent,
        "scope": plan.scope_detection.primary_scope,
        "strategy": plan.strategy,
        "retrieval_source": plan.retrieval_plan.source,
    }
    if max_alternate_queries is not None:
        meta["max_alternate_queries"] = max_alternate_queries
    if reason is not None:
        meta["reason"] = reason
    return meta
