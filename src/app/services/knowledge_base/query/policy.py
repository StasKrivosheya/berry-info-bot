from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from app.services.knowledge_base.query.classifier import classify_query_intent
from app.services.knowledge_base.query.config import (
    KnowledgeBaseQuerySettings,
    get_kb_query_settings,
)
from app.services.knowledge_base.query.llm import (
    OpenAIQueryInterpreter,
    QueryInterpretationRequest,
    QueryInterpretationResult,
    QueryInterpreter,
)
from app.services.knowledge_base.query.planner import (
    build_query_plan_with_strategy,
    strategy_for_intent,
    strategy_matches_intent,
    strategy_requirements,
)
from app.services.knowledge_base.query.retrieval_planner import (
    build_deterministic_retrieval_plan,
    build_retrieval_plan_from_hints,
)
from app.services.knowledge_base.query.scope import detect_query_scope
from app.services.knowledge_base.query.text import normalize_query_text
from app.services.knowledge_base.query.types import (
    QueryClassification,
    QueryDecisionSource,
    QueryInterpretationStage,
    QueryLLMMode,
    QueryPlan,
    QueryPolicyTrace,
    QueryRetrievalPlan,
    QueryScopeDetection,
    QueryStrategy,
)

logger = logging.getLogger(__name__)

LOG_EVENT_POLICY_RESOLVED = "kb_query_policy_resolved"
LOG_EVENT_POLICY_LLM_REQUESTED = "kb_query_policy_llm_requested"
LOG_EVENT_POLICY_LLM_SKIPPED = "kb_query_policy_llm_skipped"
LOG_EVENT_POLICY_LLM_FAILED = "kb_query_policy_llm_failed"


@dataclass(slots=True)
class _DeterministicBaseline:
    classification: QueryClassification
    scope: QueryScopeDetection
    strategy: QueryStrategy
    retrieval_plan: QueryRetrievalPlan


@dataclass(slots=True)
class _LLMResolution:
    requested_stages: tuple[QueryInterpretationStage, ...]
    skip_reason: str | None
    result: QueryInterpretationResult | None
    cache_hit: bool
    failure_reason: str | None
    debug_note: str | None


@dataclass(slots=True)
class _FinalDecisions:
    classification: QueryClassification
    scope: QueryScopeDetection
    strategy: QueryStrategy
    retrieval_plan: QueryRetrievalPlan
    intent_source: QueryDecisionSource
    scope_source: QueryDecisionSource
    strategy_source: QueryDecisionSource
    retrieval_source: QueryDecisionSource
    llm_failure_reason: str | None


class KnowledgeBaseQueryPolicy:
    """Rules-first query routing policy with optional structured LLM fallback."""

    def __init__(
        self,
        *,
        settings: KnowledgeBaseQuerySettings | None = None,
        llm_interpreter: QueryInterpreter | None = None,
    ) -> None:
        self._settings = settings or get_kb_query_settings()
        self._llm_interpreter = llm_interpreter
        self._cache: OrderedDict[tuple[Any, ...], QueryInterpretationResult] = OrderedDict()

    @property
    def settings(self) -> KnowledgeBaseQuerySettings:
        return self._settings

    def resolve_query_plan(
        self,
        query: str,
        *,
        llm_mode_override: QueryLLMMode | None = None,
    ) -> QueryPlan:
        llm_mode = llm_mode_override or self._settings.kb_query_llm_mode
        stage_toggles = self._settings.stage_toggles

        baseline = self._build_deterministic_baseline(
            query=query,
            stage_toggles=stage_toggles,
        )
        llm_resolution = self._resolve_llm_resolution(
            query=query,
            llm_mode=llm_mode,
            baseline=baseline,
        )
        final = self._resolve_final_decisions(
            query=query,
            stage_toggles=stage_toggles,
            baseline=baseline,
            llm_resolution=llm_resolution,
        )
        base_plan = build_query_plan_with_strategy(
            final.classification,
            final.scope,
            final.retrieval_plan,
            final.strategy,
        )
        policy_trace = QueryPolicyTrace(
            mode=llm_mode,
            llm_allowed_for=self._settings.kb_query_llm_allowed_for,
            stage_toggles=stage_toggles,
            rules_min_confidence=self._settings.kb_query_rules_min_confidence,
            deterministic_classification=baseline.classification,
            deterministic_scope_detection=baseline.scope,
            deterministic_strategy=baseline.strategy,
            deterministic_retrieval_plan=baseline.retrieval_plan,
            final_intent_source=final.intent_source,
            final_scope_source=final.scope_source,
            final_strategy_source=final.strategy_source,
            final_retrieval_source=final.retrieval_source,
            llm_requested=bool(llm_resolution.requested_stages),
            llm_used=llm_resolution.result is not None,
            llm_cache_hit=llm_resolution.cache_hit,
            llm_stages_requested=llm_resolution.requested_stages,
            llm_skip_reason=llm_resolution.skip_reason,
            llm_failure_reason=final.llm_failure_reason,
            llm_debug_note=llm_resolution.debug_note,
        )
        rationale = list(base_plan.rationale)
        rationale.extend(
            note for note in final.retrieval_plan.rationale if note and note not in rationale
        )
        if not stage_toggles.planner_enabled and final.strategy_source == "default":
            rationale.append("Planner stage is disabled; using safe fallback strategy.")

        plan = QueryPlan(
            classification=base_plan.classification,
            scope_detection=base_plan.scope_detection,
            strategy=base_plan.strategy,
            retrieval_plan=base_plan.retrieval_plan,
            needs_retrieval=base_plan.needs_retrieval,
            needs_structure=base_plan.needs_structure,
            rationale=tuple(rationale),
            strategy_source=final.strategy_source,
            policy_trace=policy_trace,
        )
        logger.info(
            (
                "%s query=%r mode=%s intent=%s intent_source=%s scope=%s scope_source=%s "
                "strategy=%s strategy_source=%s retrieval_source=%s llm_requested=%s "
                "llm_used=%s llm_cache_hit=%s llm_failure_reason=%s"
            ),
            LOG_EVENT_POLICY_RESOLVED,
            query,
            llm_mode,
            plan.intent,
            final.intent_source,
            plan.scope_detection.primary_scope,
            final.scope_source,
            plan.strategy,
            final.strategy_source,
            final.retrieval_source,
            policy_trace.llm_requested,
            policy_trace.llm_used,
            policy_trace.llm_cache_hit,
            policy_trace.llm_failure_reason,
        )
        return plan

    def _build_deterministic_baseline(
        self,
        *,
        query: str,
        stage_toggles,
    ) -> _DeterministicBaseline:
        classification = (
            classify_query_intent(query)
            if stage_toggles.rules_enabled
            else _default_classification("Rules stage disabled by configuration.")
        )
        scope = (
            detect_query_scope(query)
            if stage_toggles.scope_enabled
            else _default_scope("Scope stage disabled by configuration.")
        )
        strategy = (
            strategy_for_intent(classification.intent)
            if stage_toggles.planner_enabled
            else "safe_fallback"
        )
        retrieval_plan = build_deterministic_retrieval_plan(
            query,
            classification,
            scope,
            strategy,
        )
        return _DeterministicBaseline(
            classification=classification,
            scope=scope,
            strategy=strategy,
            retrieval_plan=retrieval_plan,
        )

    def _resolve_llm_resolution(
        self,
        *,
        query: str,
        llm_mode: QueryLLMMode,
        baseline: _DeterministicBaseline,
    ) -> _LLMResolution:
        normalized_query = normalize_query_text(query)
        requested_stages, llm_skip_reason = self._determine_llm_stages(
            mode=llm_mode,
            deterministic_classification=baseline.classification,
            deterministic_scope=baseline.scope,
            deterministic_strategy=baseline.strategy,
            deterministic_retrieval_plan=baseline.retrieval_plan,
        )

        llm_result = None
        llm_cache_hit = False
        llm_failure_reason = None
        llm_debug_note = None
        if requested_stages:
            logger.debug(
                "%s query=%r stages=%s mode=%s",
                LOG_EVENT_POLICY_LLM_REQUESTED,
                query,
                requested_stages,
                llm_mode,
            )
            llm_result, llm_cache_hit, llm_failure_reason = self._interpret_with_llm(
                query=query,
                normalized_query=normalized_query,
                requested_stages=requested_stages,
                deterministic_classification=baseline.classification,
                deterministic_scope=baseline.scope,
                deterministic_strategy=baseline.strategy,
                deterministic_retrieval_plan=baseline.retrieval_plan,
            )
            if llm_result is not None:
                llm_debug_note = llm_result.debug_note or (
                    llm_result.retrieval_hints.debug_note
                    if llm_result.retrieval_hints is not None
                    else None
                )
        else:
            logger.debug(
                "%s query=%r reason=%s mode=%s",
                LOG_EVENT_POLICY_LLM_SKIPPED,
                query,
                llm_skip_reason,
                llm_mode,
            )

        return _LLMResolution(
            requested_stages=requested_stages,
            skip_reason=llm_skip_reason,
            result=llm_result,
            cache_hit=llm_cache_hit,
            failure_reason=llm_failure_reason,
            debug_note=llm_debug_note,
        )

    def _resolve_final_decisions(
        self,
        *,
        query: str,
        stage_toggles,
        baseline: _DeterministicBaseline,
        llm_resolution: _LLMResolution,
    ) -> _FinalDecisions:
        llm_result = llm_resolution.result
        requested_stages = llm_resolution.requested_stages
        llm_failure_reason = llm_resolution.failure_reason

        final_classification = baseline.classification
        final_scope = baseline.scope
        final_strategy = baseline.strategy if stage_toggles.planner_enabled else "safe_fallback"
        final_retrieval_plan = baseline.retrieval_plan
        final_intent_source: QueryDecisionSource = baseline.classification.source
        final_scope_source: QueryDecisionSource = baseline.scope.source
        final_strategy_source: QueryDecisionSource = (
            "rules" if stage_toggles.planner_enabled else "default"
        )
        final_retrieval_source: QueryDecisionSource = baseline.retrieval_plan.source

        if llm_result is not None and "classifier" in requested_stages:
            final_classification = QueryClassification(
                intent=llm_result.intent,
                confidence=llm_result.confidence,
                rationale=_llm_rationale(
                    llm_result.debug_note,
                    "LLM fallback classified the query.",
                ),
                source="llm",
            )
            final_intent_source = "llm"

        if llm_result is not None and "scope" in requested_stages:
            final_scope = QueryScopeDetection(
                primary_scope=llm_result.scope,
                scopes=(llm_result.scope,),
                confidence=llm_result.confidence,
                rationale=_llm_rationale(
                    llm_result.debug_note,
                    "LLM fallback selected the query scope.",
                ),
                source="llm",
            )
            final_scope_source = "llm"

        if stage_toggles.planner_enabled:
            final_strategy = strategy_for_intent(final_classification.intent)
            final_strategy_source = "rules"
        else:
            final_strategy = "safe_fallback"
            final_strategy_source = "default"

        if llm_result is not None and "planner" in requested_stages:
            if strategy_matches_intent(final_classification.intent, llm_result.strategy):
                final_strategy = llm_result.strategy
                final_strategy_source = "llm"
            else:
                llm_failure_reason = _combine_reason(
                    llm_failure_reason,
                    "invalid_llm_strategy_for_intent",
                )

        if llm_result is not None and "retrieval" in requested_stages:
            if llm_result.retrieval_hints is None:
                llm_failure_reason = _combine_reason(
                    llm_failure_reason,
                    "missing_llm_retrieval_hints",
                )
            else:
                final_retrieval_plan = build_retrieval_plan_from_hints(
                    default_query=query,
                    hints=llm_result.retrieval_hints,
                    source="llm",
                    rationale=_llm_rationale(
                        llm_result.retrieval_hints.debug_note,
                        "Structured LLM fallback supplied retrieval hints.",
                    ),
                )
                final_retrieval_source = "llm"

        return _FinalDecisions(
            classification=final_classification,
            scope=final_scope,
            strategy=final_strategy,
            retrieval_plan=final_retrieval_plan,
            intent_source=final_intent_source,
            scope_source=final_scope_source,
            strategy_source=final_strategy_source,
            retrieval_source=final_retrieval_source,
            llm_failure_reason=llm_failure_reason,
        )

    def _determine_llm_stages(
        self,
        *,
        mode: QueryLLMMode,
        deterministic_classification: QueryClassification,
        deterministic_scope: QueryScopeDetection,
        deterministic_strategy: QueryStrategy,
        deterministic_retrieval_plan: QueryRetrievalPlan,
    ) -> tuple[tuple[QueryInterpretationStage, ...], str | None]:
        if mode == "disabled":
            return (), "llm_disabled_by_mode"

        allowed = set(self._settings.kb_query_llm_allowed_for)
        if not allowed:
            return (), "llm_not_allowed_for_any_stage"

        stage_toggles = self._settings.stage_toggles
        threshold = self._settings.kb_query_rules_min_confidence
        classifier_needed = False
        scope_needed = False
        planner_needed = False
        retrieval_needed = False

        if mode == "forced":
            classifier_needed = "classifier" in allowed
            scope_needed = "scope" in allowed
            planner_needed = "planner" in allowed
            retrieval_needed = "retrieval" in allowed and stage_toggles.retrieval_enabled
        else:
            classifier_needed = (
                "classifier" in allowed
                and (
                    not stage_toggles.rules_enabled
                    or deterministic_classification.intent == "unknown"
                    or deterministic_classification.confidence < threshold
                )
            )
            scope_needed = "scope" in allowed and (
                not stage_toggles.scope_enabled
                or (
                    classifier_needed
                    and (
                        deterministic_scope.primary_scope == "general"
                        or deterministic_scope.confidence < threshold
                    )
                )
                or (
                    deterministic_classification.intent in {"detail", "comparison"}
                    and (
                        deterministic_scope.primary_scope == "general"
                        or deterministic_scope.confidence < threshold
                    )
                )
            )
            planner_needed = "planner" in allowed and (
                not stage_toggles.planner_enabled
                or deterministic_strategy == "safe_fallback"
                or classifier_needed
                or scope_needed
            )
            retrieval_needed = "retrieval" in allowed and stage_toggles.retrieval_enabled and (
                classifier_needed
                or scope_needed
                or planner_needed
                or (
                    strategy_requirements(deterministic_strategy)[0]
                    and (
                        deterministic_scope.primary_scope == "general"
                        or deterministic_scope.confidence < threshold
                        or _is_baseline_retrieval_plan(deterministic_retrieval_plan)
                    )
                )
            )

        requested = tuple(
            stage
            for stage, enabled in (
                ("classifier", classifier_needed),
                ("scope", scope_needed),
                ("planner", planner_needed),
                ("retrieval", retrieval_needed),
            )
            if enabled
        )
        if requested:
            return requested, None
        return (), "deterministic_pipeline_sufficient"

    def _interpret_with_llm(
        self,
        *,
        query: str,
        normalized_query: str,
        requested_stages: tuple[QueryInterpretationStage, ...],
        deterministic_classification: QueryClassification,
        deterministic_scope: QueryScopeDetection,
        deterministic_strategy: QueryStrategy,
        deterministic_retrieval_plan: QueryRetrievalPlan,
    ) -> tuple[QueryInterpretationResult | None, bool, str | None]:
        request = QueryInterpretationRequest(
            query=query,
            normalized_query=normalized_query,
            requested_stages=requested_stages,
            deterministic_classification=deterministic_classification,
            deterministic_scope_detection=deterministic_scope,
            deterministic_strategy=deterministic_strategy,
            deterministic_retrieval_plan=deterministic_retrieval_plan,
        )
        cache_hit, cached = self._get_cached_result(request)
        if cached is not None:
            return cached, cache_hit, None

        try:
            interpreter = self._get_llm_interpreter()
        except RuntimeError as exc:
            reason = str(exc)
            logger.info("%s query=%r reason=%s", LOG_EVENT_POLICY_LLM_FAILED, query, reason)
            return None, False, reason

        try:
            result = interpreter.interpret(request)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "%s query=%r reason=%s",
                LOG_EVENT_POLICY_LLM_FAILED,
                query,
                reason,
                exc_info=True,
            )
            return None, False, reason

        self._store_cached_result(request, result)
        return result, False, None

    def _get_llm_interpreter(self) -> QueryInterpreter:
        if self._llm_interpreter is not None:
            return self._llm_interpreter

        api_key = self._settings.llm_api_key
        model = self._settings.kb_query_llm_model
        if api_key is None:
            raise RuntimeError("llm_unavailable:missing_openai_api_key")
        if model is None:
            raise RuntimeError("llm_unavailable:missing_kb_query_llm_model")

        self._llm_interpreter = OpenAIQueryInterpreter(
            api_key=api_key,
            model=model,
            timeout_seconds=self._settings.kb_query_llm_timeout_seconds,
        )
        return self._llm_interpreter

    def _get_cached_result(
        self,
        request: QueryInterpretationRequest,
    ) -> tuple[bool, QueryInterpretationResult | None]:
        if self._settings.kb_query_llm_cache_size <= 0:
            return False, None

        cache_key = _cache_key_for_request(request)
        cached = self._cache.get(cache_key)
        if cached is None:
            return False, None

        self._cache.move_to_end(cache_key)
        return True, cached

    def _store_cached_result(
        self,
        request: QueryInterpretationRequest,
        result: QueryInterpretationResult,
    ) -> None:
        if self._settings.kb_query_llm_cache_size <= 0:
            return

        cache_key = _cache_key_for_request(request)
        self._cache[cache_key] = result
        self._cache.move_to_end(cache_key)
        while len(self._cache) > self._settings.kb_query_llm_cache_size:
            self._cache.popitem(last=False)


def _default_classification(reason: str) -> QueryClassification:
    return QueryClassification(
        intent="unknown",
        confidence=0.0,
        rationale=(reason,),
        source="default",
    )


def _default_scope(reason: str) -> QueryScopeDetection:
    return QueryScopeDetection(
        primary_scope="general",
        scopes=("general",),
        confidence=0.0,
        rationale=(reason,),
        source="default",
    )


def _llm_rationale(debug_note: str | None, fallback_note: str) -> tuple[str, ...]:
    if debug_note:
        return (fallback_note, debug_note)
    return (fallback_note,)


def _cache_key_for_request(request: QueryInterpretationRequest) -> tuple[Any, ...]:
    return (
        request.normalized_query,
        request.requested_stages,
        request.deterministic_classification.intent,
        request.deterministic_classification.confidence,
        request.deterministic_scope_detection.primary_scope,
        request.deterministic_scope_detection.confidence,
        request.deterministic_strategy,
        request.deterministic_retrieval_plan.primary_query,
        request.deterministic_retrieval_plan.alternate_queries,
        request.deterministic_retrieval_plan.keywords,
    )


def _combine_reason(existing: str | None, new_reason: str) -> str:
    if existing is None:
        return new_reason
    return f"{existing};{new_reason}"


def _is_baseline_retrieval_plan(plan: QueryRetrievalPlan) -> bool:
    return (
        plan.confidence <= 0.0
        and not plan.alternate_queries
        and not plan.keywords
    )
