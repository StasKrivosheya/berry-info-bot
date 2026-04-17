# ruff: noqa: RUF001

from __future__ import annotations

import json
import os
from pathlib import Path

from app.services.knowledge_base.query.config import KnowledgeBaseQuerySettings
from app.services.knowledge_base.query.llm import (
    QueryInterpretationRequest,
    QueryInterpretationResult,
)
from app.services.knowledge_base.query.pipeline import KnowledgeBaseQueryPipeline
from app.services.knowledge_base.query.structure import KnowledgeBaseStructureReader
from app.services.knowledge_base.query.types import QueryRetrievalHints
from app.services.knowledge_base.types_openai import SearchHit, SearchResponse


class FakeLLMInterpreter:
    def __init__(
        self,
        *,
        result: QueryInterpretationResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.calls: list[QueryInterpretationRequest] = []

    def interpret(self, request: QueryInterpretationRequest) -> QueryInterpretationResult:
        self.calls.append(request)
        if self._error is not None:
            raise self._error
        if self._result is None:
            msg = "FakeLLMInterpreter requires result or error."
            raise RuntimeError(msg)
        return self._result


class FakeRetriever:
    def __init__(self, response: SearchResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> SearchResponse:
        self.calls.append(kwargs)
        return self.response


def _settings(**overrides) -> KnowledgeBaseQuerySettings:
    values = {
        "kb_query_llm_mode": "disabled",
        "kb_query_llm_allowed_for": ("classifier", "scope", "planner", "retrieval"),
        "kb_query_rules_min_confidence": 0.85,
        "kb_query_enable_stage_rules": True,
        "kb_query_enable_stage_scope": True,
        "kb_query_enable_stage_planner": True,
        "kb_query_enable_stage_retrieval": True,
        "kb_query_enable_stage_renderer": True,
        "kb_query_llm_model": None,
        "kb_query_llm_timeout_seconds": 10,
        "kb_query_llm_cache_size": 128,
        "kb_query_llm_max_retrieval_variants": 1,
        "openai_api_key": None,
    }
    values.update(overrides)
    return KnowledgeBaseQuerySettings(_env_file=None, **values)


def _write_manifest(tmp_path: Path) -> Path:
    output_dir = tmp_path / "processed"
    markdown_dir = output_dir / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)

    (markdown_dir / "programs.md").write_text(
        ("# Організовані програми\n\n## ВИДИ ПРОГРАМ\n\n## Програма А\n\n## Програма Б\n"),
        encoding="utf-8",
    )
    (markdown_dir / "park.md").write_text(
        (
            "# Сімейний відпочинок\n\n"
            "### Що входить у вартість квитка?\n\n"
            "✔ Ігрова зона\n"
            "✔ Поні-ферма\n"
        ),
        encoding="utf-8",
    )

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "output_dir": output_dir.as_posix(),
                "entries": [
                    {
                        "source_file": "kb.xlsx",
                        "source_format": "xlsx",
                        "sheet_name": "Programs",
                        "sheet_index": 1,
                        "workbook_file": "kb.xlsx",
                        "output_md_file": ["markdown/programs.md"],
                        "logical_id": "programs",
                        "category": "programs",
                        "version": "1.0",
                        "updated_at_utc": "2026-04-02T00:00:00+00:00",
                        "content_hash_sha256": "hash-programs",
                    },
                    {
                        "source_file": "kb.xlsx",
                        "source_format": "xlsx",
                        "sheet_name": "Park",
                        "sheet_index": 2,
                        "workbook_file": "kb.xlsx",
                        "output_md_file": ["markdown/park.md"],
                        "logical_id": "park",
                        "category": "park",
                        "version": "1.0",
                        "updated_at_utc": "2026-04-02T00:00:00+00:00",
                        "content_hash_sha256": "hash-park",
                    },
                ],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def _search_response(*, logical_id: str, text: str, score: float = 0.88) -> SearchResponse:
    return SearchResponse(
        results=[
            SearchHit(
                file_id=f"file_{logical_id}",
                filename=f"{logical_id}.md",
                score=score,
                attributes={"logical_id": logical_id, "category": logical_id, "language": "uk"},
                text=text,
            )
        ],
        top_score=score,
        used_threshold=0.7,
        fallback_triggered=False,
        fallback_message=None,
    )


def test_llm_disabled_uses_deterministic_rules_only() -> None:
    interpreter = FakeLLMInterpreter(
        result=QueryInterpretationResult(
            intent="overview",
            scope="general",
            strategy="overview_summary",
            confidence=0.9,
        )
    )
    pipeline = KnowledgeBaseQueryPipeline(
        policy_settings=_settings(kb_query_llm_mode="disabled"),
        llm_interpreter=interpreter,
    )

    plan = pipeline.plan_query("Які є види організованих програм?")

    assert interpreter.calls == []
    assert plan.intent == "enumeration"
    assert plan.classification.source == "rules"
    assert plan.policy_trace.llm_requested is False
    assert plan.policy_trace.llm_skip_reason == "llm_disabled_by_mode"


def test_fallback_mode_skips_llm_for_confident_rules() -> None:
    interpreter = FakeLLMInterpreter(
        result=QueryInterpretationResult(
            intent="overview",
            scope="general",
            strategy="overview_summary",
            confidence=0.9,
        )
    )
    pipeline = KnowledgeBaseQueryPipeline(
        policy_settings=_settings(kb_query_llm_mode="fallback"),
        llm_interpreter=interpreter,
    )

    plan = pipeline.plan_query("Що ви можете мені запропонувати?")

    assert interpreter.calls == []
    assert plan.intent == "overview"
    assert plan.classification.source == "rules"
    assert plan.policy_trace.llm_requested is False
    assert plan.policy_trace.llm_skip_reason == "deterministic_pipeline_sufficient"


def test_fallback_mode_uses_llm_for_uncertain_queries() -> None:
    interpreter = FakeLLMInterpreter(
        result=QueryInterpretationResult(
            intent="overview",
            scope="park_activities",
            strategy="overview_summary",
            confidence=0.91,
            debug_note="Broad park offer query.",
            retrieval_hints=QueryRetrievalHints(
                primary_query="активності в парку Berry Land",
                alternate_queries=("поні-ферма активності",),
                keywords=("активності", "поні-ферма"),
                confidence=0.83,
            ),
        )
    )
    pipeline = KnowledgeBaseQueryPipeline(
        policy_settings=_settings(kb_query_llm_mode="fallback"),
        llm_interpreter=interpreter,
    )

    plan = pipeline.plan_query("Розкажи щось цікаве")

    assert len(interpreter.calls) == 1
    assert plan.intent == "overview"
    assert plan.classification.source == "llm"
    assert plan.scope_detection.primary_scope == "park_activities"
    assert plan.scope_detection.source == "llm"
    assert plan.strategy == "overview_summary"
    assert plan.strategy_source == "llm"
    assert plan.retrieval_plan.source == "llm"
    assert plan.retrieval_plan.primary_query == "активності в парку Berry Land"
    assert plan.policy_trace.llm_requested is True
    assert plan.policy_trace.llm_used is True


def test_forced_mode_always_uses_llm_for_interpretation() -> None:
    interpreter = FakeLLMInterpreter(
        result=QueryInterpretationResult(
            intent="overview",
            scope="programs",
            strategy="overview_summary",
            confidence=0.87,
            retrieval_hints=QueryRetrievalHints(
                primary_query="організовані програми Berry Land",
                alternate_queries=("види програм Berry Land",),
                keywords=("організовані програми",),
                confidence=0.85,
            ),
        )
    )
    pipeline = KnowledgeBaseQueryPipeline(
        policy_settings=_settings(kb_query_llm_mode="forced"),
        llm_interpreter=interpreter,
    )

    plan = pipeline.plan_query("Які є види організованих програм?")

    assert len(interpreter.calls) == 1
    assert plan.classification.source == "llm"
    assert plan.scope_detection.source == "llm"
    assert plan.strategy_source == "llm"
    assert plan.retrieval_plan.source == "llm"
    assert plan.policy_trace.llm_stages_requested == (
        "classifier",
        "scope",
        "planner",
        "retrieval",
    )


def test_llm_failure_falls_back_safely_to_deterministic_pipeline() -> None:
    interpreter = FakeLLMInterpreter(error=TimeoutError("LLM timed out"))
    pipeline = KnowledgeBaseQueryPipeline(
        policy_settings=_settings(kb_query_llm_mode="fallback"),
        llm_interpreter=interpreter,
    )

    plan = pipeline.plan_query("Порадь щось для відпочинку")

    assert len(interpreter.calls) == 1
    assert plan.intent == "unknown"
    assert plan.classification.source == "rules"
    assert plan.strategy == "safe_fallback"
    assert plan.strategy_source == "rules"
    assert plan.policy_trace.llm_used is False
    assert "TimeoutError" in str(plan.policy_trace.llm_failure_reason)


def test_invalid_llm_strategy_is_ignored_safely() -> None:
    interpreter = FakeLLMInterpreter(
        result=QueryInterpretationResult(
            intent="overview",
            scope="programs",
            strategy="detail_retrieval",
            confidence=0.9,
            retrieval_hints=QueryRetrievalHints(
                primary_query="організовані програми Berry Land",
                alternate_queries=(),
                keywords=("організовані програми",),
                confidence=0.84,
            ),
        )
    )
    pipeline = KnowledgeBaseQueryPipeline(
        policy_settings=_settings(kb_query_llm_mode="forced"),
        llm_interpreter=interpreter,
    )

    plan = pipeline.plan_query("Які є види організованих програм?")

    assert plan.intent == "overview"
    assert plan.classification.source == "llm"
    assert plan.strategy == "overview_summary"
    assert plan.strategy_source == "rules"
    assert plan.retrieval_plan.source == "llm"
    assert "invalid_llm_strategy_for_intent" in str(plan.policy_trace.llm_failure_reason)


def test_uncertain_query_interpretation_is_cached() -> None:
    interpreter = FakeLLMInterpreter(
        result=QueryInterpretationResult(
            intent="overview",
            scope="general",
            strategy="overview_summary",
            confidence=0.82,
            retrieval_hints=QueryRetrievalHints(
                primary_query="відпочинок Berry Land",
                alternate_queries=("активності в парку",),
                keywords=("відпочинок",),
                confidence=0.8,
            ),
        )
    )
    pipeline = KnowledgeBaseQueryPipeline(
        policy_settings=_settings(kb_query_llm_mode="fallback", kb_query_llm_cache_size=8),
        llm_interpreter=interpreter,
    )

    first_plan = pipeline.plan_query("Порадь щось для відпочинку")
    second_plan = pipeline.plan_query("Порадь щось для відпочинку")

    assert len(interpreter.calls) == 1
    assert first_plan.policy_trace.llm_cache_hit is False
    assert second_plan.policy_trace.llm_cache_hit is True


def test_retrieval_stage_can_be_disabled_safely(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    retriever = FakeRetriever(_search_response(logical_id="park", text="Поні-ферма"))
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=_settings(
            kb_query_enable_stage_retrieval=False,
            kb_query_enable_stage_renderer=True,
        ),
    )

    inspection = pipeline.inspect_query("Чи є у вас поні-ферма?")
    assert inspection.answer_result is not None
    result = inspection.answer_result

    assert retriever.calls == []
    assert inspection.route_context.policy_trace.stage_toggles.retrieval_enabled is False
    assert result.state == "fallback"
    assert inspection.retrieval_trace is not None
    assert inspection.retrieval_trace.stop_reason == "retrieval_disabled_by_configuration"


def test_renderer_stage_can_be_disabled_safely(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    retriever = FakeRetriever(_search_response(logical_id="park", text="Поні-ферма"))
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=_settings(
            kb_query_enable_stage_retrieval=True,
            kb_query_enable_stage_renderer=False,
        ),
    )

    inspection = pipeline.inspect_query("Чи є у вас поні-ферма?")
    assert inspection.answer_result is not None
    result = inspection.answer_result

    assert retriever.calls == [
        {
            "query": "Чи є у вас поні-ферма?",
            "max_num_results": None,
            "rewrite_query": False,
            "score_threshold": None,
            "category": None,
            "logical_id": None,
            "attribute_filters": None,
        }
    ]
    assert result.answer_text == "Renderer stage is disabled by configuration."
    assert result.source_section_ids == ()
    assert result.state == "fallback"
    assert inspection.retrieval_trace is not None
    assert inspection.retrieval_trace.executed_queries == ("Чи є у вас поні-ферма?",)


def test_settings_accept_comma_separated_llm_allowed_for_from_env(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.test"
    env_path.write_text(
        "\n".join(
            (
                "KB_QUERY_LLM_MODE=forced",
                "KB_QUERY_LLM_ALLOWED_FOR=classifier,scope,planner,retrieval",
            )
        ),
        encoding="utf-8",
    )

    previous = os.environ.get("KB_QUERY_LLM_ALLOWED_FOR")
    os.environ.pop("KB_QUERY_LLM_ALLOWED_FOR", None)
    try:
        settings = KnowledgeBaseQuerySettings(_env_file=env_path)
    finally:
        if previous is not None:
            os.environ["KB_QUERY_LLM_ALLOWED_FOR"] = previous

    assert settings.kb_query_llm_mode == "forced"
    assert settings.kb_query_llm_allowed_for == (
        "classifier",
        "scope",
        "planner",
        "retrieval",
    )


def test_deterministic_retrieval_planner_expands_zoo_wording_without_llm() -> None:
    pipeline = KnowledgeBaseQueryPipeline(
        policy_settings=_settings(kb_query_llm_mode="disabled"),
    )

    plan = pipeline.plan_query("хто у вас є в зоопарку?")

    assert plan.retrieval_plan.source == "rules"
    assert "поні-ферму" in plan.retrieval_plan.primary_query
    assert "тварини" in plan.retrieval_plan.keywords


def test_fallback_mode_requests_retrieval_hints_for_baseline_ambiguous_queries() -> None:
    interpreter = FakeLLMInterpreter(
        result=QueryInterpretationResult(
            intent="detail",
            scope="park_activities",
            strategy="detail_retrieval",
            confidence=0.9,
            retrieval_hints=QueryRetrievalHints(
                primary_query="екскурсія на поні-ферму тварини ранчо",
                alternate_queries=("ферма до тваринок Berry Land",),
                keywords=("поні-ферма", "тварини", "ранчо"),
                confidence=0.9,
            ),
        )
    )
    pipeline = KnowledgeBaseQueryPipeline(
        policy_settings=_settings(kb_query_llm_mode="fallback"),
        llm_interpreter=interpreter,
    )

    plan = pipeline.plan_query("хто у вас є в зоопарку?")

    assert len(interpreter.calls) == 1
    assert "retrieval" in plan.policy_trace.llm_stages_requested
    assert plan.retrieval_plan.source == "llm"
    assert "поні-ферму" in plan.retrieval_plan.primary_query
