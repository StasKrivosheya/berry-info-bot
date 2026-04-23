# ruff: noqa: RUF001

from __future__ import annotations

import json
from pathlib import Path

from app.services.knowledge_base.query.classifier import classify_query_intent
from app.services.knowledge_base.query.config import KnowledgeBaseQuerySettings
from app.services.knowledge_base.query.dto import AnswerResult
from app.services.knowledge_base.query.execution import execute_query_plan
from app.services.knowledge_base.query.llm import (
    QueryInterpretationRequest,
    QueryInterpretationResult,
)
from app.services.knowledge_base.query.pipeline import KnowledgeBaseQueryPipeline
from app.services.knowledge_base.query.planner import build_query_plan
from app.services.knowledge_base.query.renderer import render_query_answer
from app.services.knowledge_base.query.retrieval_planner import build_deterministic_retrieval_plan
from app.services.knowledge_base.query.scope import detect_query_scope
from app.services.knowledge_base.query.structure import KnowledgeBaseStructureReader
from app.services.knowledge_base.query.types import (
    QueryClassification,
    QueryPolicyTrace,
    QueryRetrievalHints,
    QueryRetrievalPlan,
    QueryRouteContext,
    QueryScopeDetection,
    StructuredDocument,
    StructuredSection,
)
from app.services.knowledge_base.types_openai import (
    NO_RELEVANT_INFO_FALLBACK,
    SearchHit,
    SearchResponse,
)


class FakeRetriever:
    def __init__(self, response: SearchResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> SearchResponse:
        self.calls.append(kwargs)
        return self.response


class MappingRetriever:
    def __init__(self, responses_by_query: dict[str, SearchResponse]) -> None:
        self.responses_by_query = responses_by_query
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> SearchResponse:
        self.calls.append(kwargs)
        query = str(kwargs["query"])
        return self.responses_by_query[query]


class FakeLLMInterpreter:
    def __init__(self, result: QueryInterpretationResult) -> None:
        self.result = result
        self.calls: list[QueryInterpretationRequest] = []

    def interpret(self, request: QueryInterpretationRequest) -> QueryInterpretationResult:
        self.calls.append(request)
        return self.result


class StaticStructureReader:
    def __init__(
        self,
        *,
        scoped_documents: tuple[StructuredDocument, ...],
        all_documents: tuple[StructuredDocument, ...],
    ) -> None:
        self.scoped_documents = scoped_documents
        self.all_documents = all_documents
        self.manifest_path = Path("test-manifest.json")

    def documents_for_scopes(self, scopes: tuple[str, ...]) -> tuple[StructuredDocument, ...]:
        return self.scoped_documents

    def load_documents(self) -> tuple[StructuredDocument, ...]:
        return self.all_documents


def _inspect_and_answer(
    pipeline: KnowledgeBaseQueryPipeline,
    query: str,
) -> tuple[object, AnswerResult]:
    inspection = pipeline.inspect_query(query)
    assert inspection.answer_result is not None
    return inspection, inspection.answer_result


def _disabled_settings() -> KnowledgeBaseQuerySettings:
    return KnowledgeBaseQuerySettings(
        _env_file=None,
        kb_query_llm_mode="disabled",
        kb_query_llm_allowed_for=("classifier", "scope", "planner", "retrieval"),
        kb_query_rules_min_confidence=0.85,
        kb_query_enable_stage_rules=True,
        kb_query_enable_stage_scope=True,
        kb_query_enable_stage_planner=True,
        kb_query_enable_stage_retrieval=True,
        kb_query_enable_stage_renderer=True,
        kb_query_llm_model=None,
        kb_query_llm_timeout_seconds=10,
        kb_query_llm_cache_size=32,
        kb_query_llm_max_retrieval_variants=1,
        openai_api_key=None,
    )


def _write_manifest(tmp_path: Path) -> Path:
    output_dir = tmp_path / "processed"
    markdown_dir = output_dir / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)

    (markdown_dir / "programs.md").write_text(
        (
            "# Організовані програми\n\n"
            "## ВИДИ ПРОГРАМ\n\n"
            "## Програма А\n\n"
            "## Програма Б\n\n"
            "## ДОДАТКОВІ ПОСЛУГИ\n\n"
            "## Трансфер з інших міст\n\n"
            "## Дніпро\n"
        ),
        encoding="utf-8",
    )
    (markdown_dir / "park.md").write_text(
        (
            "# Сімейний відпочинок\n\n"
            "### Що входить у вартість квитка?\n\n"
            "✔ Ігрова зона\n"
            "✔ Поні-ферма\n\n"
            "## Додаткові послуги на території парку\n\n"
            "• Альтанки з мангалом\n"
            "• Кафе та бар\n"
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


def _write_schedule_manifest(tmp_path: Path) -> Path:
    output_dir = tmp_path / "processed"
    markdown_dir = output_dir / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)

    (markdown_dir / "schedule.md").write_text(
        (
            "# Св (Квітень Травень)\n\n"
            "Сімейний відпочинок у Berry Land.\n\n"
            "📅 Графік роботи:\n"
            "• Парк працює по суботах та неділях\n"
            "• Час роботи: з 10:00 до 19:00\n\n"
            "## Що входить у вартість квитка?\n\n"
            "• Вхід на територію\n"
            "• Ігрова зона\n\n"
            "## Додаткові послуги на території парку\n\n"
            "• Альтанки з мангалом\n"
            "• Кафе та бар\n"
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
                        "sheet_name": "Schedule",
                        "sheet_index": 1,
                        "workbook_file": "kb.xlsx",
                        "output_md_file": ["markdown/schedule.md"],
                        "logical_id": "schedule",
                        "category": "park",
                        "version": "1.0",
                        "updated_at_utc": "2026-04-08T00:00:00+00:00",
                        "content_hash_sha256": "hash-schedule",
                    }
                ],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def _write_animals_manifest(tmp_path: Path) -> Path:
    output_dir = tmp_path / "processed"
    markdown_dir = output_dir / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)

    (markdown_dir / "animals.md").write_text(
        (
            "# Парк пригод\n\n"
            "## Випускний Level 4.0\n\n"
            "• Вхід на територію\n"
            "• Водні розваги\n"
            "• Екскурсія на поні-ферму\n\n"
            "## Екскурсія на ферму\n\n"
            "• Знайомство з поні, козликами, альпакою та догляд за тваринами.\n"
            "• Мешканці ранчо чекають на гостей.\n"
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
                        "sheet_name": "Animals",
                        "sheet_index": 1,
                        "workbook_file": "kb.xlsx",
                        "output_md_file": ["markdown/animals.md"],
                        "logical_id": "animals",
                        "category": "park",
                        "version": "1.0",
                        "updated_at_utc": "2026-04-08T00:00:00+00:00",
                        "content_hash_sha256": "hash-animals",
                    }
                ],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def _write_services_manifest(tmp_path: Path) -> Path:
    output_dir = tmp_path / "processed"
    markdown_dir = output_dir / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)

    (markdown_dir / "services.md").write_text(
        (
            "# Додаткові послуги\n\n"
            "## Активності на воді\n\n"
            "• Катання на катамаранах — 150 грн\n"
            "• Катання на байдарках — 100 грн\n\n"
            "## Оренда та послуги\n\n"
            "• Велика альтанка — 2500 грн\n"
            "• Трансфер — 4000 грн\n"
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
                        "sheet_name": "Services",
                        "sheet_index": 1,
                        "workbook_file": "kb.xlsx",
                        "output_md_file": ["markdown/services.md"],
                        "logical_id": "services",
                        "category": "services",
                        "version": "1.0",
                        "updated_at_utc": "2026-04-08T00:00:00+00:00",
                        "content_hash_sha256": "hash-services",
                    }
                ],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def _search_response(*, logical_id: str, text: str) -> SearchResponse:
    return SearchResponse(
        results=[
            SearchHit(
                file_id=f"file_{logical_id}",
                filename=f"{logical_id}.md",
                score=0.84,
                attributes={"logical_id": logical_id, "category": logical_id, "language": "uk"},
                text=text,
            )
        ],
        top_score=0.84,
        used_threshold=0.7,
        fallback_triggered=False,
        fallback_message=None,
    )


def _search_response_with_score(*, logical_id: str, text: str, score: float) -> SearchResponse:
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


def test_classifier_returns_enumeration_for_program_list_query() -> None:
    classification = classify_query_intent("Які є види організованих програм?")

    assert classification.intent == "enumeration"
    assert classification.confidence >= 0.9
    assert any(rule.rule_id == "enumeration_program_types" for rule in classification.matched_rules)


def test_classifier_returns_overview_for_general_offer_query() -> None:
    classification = classify_query_intent("Що ви можете мені запропонувати?")

    assert classification.intent == "overview"
    assert classification.confidence >= 0.9
    assert any(rule.rule_id == "overview_offer_request" for rule in classification.matched_rules)


def test_planner_maps_detail_query_to_detail_retrieval_strategy() -> None:
    classification = classify_query_intent("Чи є у вас поні-ферма?")
    scope_detection = detect_query_scope("Чи є у вас поні-ферма?")
    retrieval_plan = build_deterministic_retrieval_plan(
        "Чи є у вас поні-ферма?",
        classification,
        scope_detection,
        "detail_retrieval",
    )

    plan = build_query_plan(classification, scope_detection, retrieval_plan)

    assert plan.intent == "detail"
    assert plan.strategy == "detail_retrieval"
    assert plan.needs_retrieval is True
    assert plan.needs_structure is True


def test_pipeline_enumeration_uses_structure_and_skips_retrieval(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    retriever = FakeRetriever(_search_response(logical_id="programs", text="Програма А"))
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=_disabled_settings(),
    )

    inspection, result = _inspect_and_answer(
        pipeline,
        "Які є види організованих програм?",
    )

    assert retriever.calls == []
    assert inspection.route_context.intent == "enumeration"
    assert inspection.route_context.strategy == "enumeration_catalog"
    assert inspection.route_context.policy_trace.mode == "disabled"
    rendered = render_query_answer(result)
    assert "Знайшов такі організовані програми:" in rendered
    assert "- Програма А" in rendered
    assert "- Програма Б" in rendered


def test_pipeline_overview_uses_structure_and_skips_retrieval(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    retriever = FakeRetriever(_search_response(logical_id="park", text="Поні-ферма"))
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=_disabled_settings(),
    )

    inspection, result = _inspect_and_answer(
        pipeline,
        "Що ви можете мені запропонувати?",
    )

    assert retriever.calls == []
    assert inspection.route_context.intent == "overview"
    assert inspection.route_context.strategy == "overview_summary"
    assert inspection.route_context.policy_trace.mode == "disabled"
    rendered = render_query_answer(result)
    assert "Організовані програми" in rendered
    assert "У парку можна" in rendered
    assert "- Ігрова зона" in rendered
    assert "- Поні-ферма" in rendered
    assert "Додаткові послуги" in rendered
    assert "- Альтанки з мангалом" in rendered


def test_pipeline_topic_program_phrase_uses_structure_catalog(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    retriever = FakeRetriever(_search_response(logical_id="programs", text="Програма А"))
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=_disabled_settings(),
    )

    program_queries = (
        "Дитячі програми",
        "які є види програм?",
        "підкажіть щодо доступних організованих програм?",
        "надайте перелік дитячих програм які можна замовити?",
    )

    for query in program_queries:
        inspection, result = _inspect_and_answer(pipeline, query)
        assert inspection.route_context.scope_detection.primary_scope == "programs"
        assert inspection.route_context.strategy == "enumeration_catalog"
        rendered = render_query_answer(result)
        assert "- Програма А" in rendered
        assert "- Програма Б" in rendered
        assert "Дніпро" not in rendered

    assert retriever.calls == []


def test_pipeline_activity_topic_phrase_uses_structure_overview(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    retriever = FakeRetriever(_search_response(logical_id="park", text="Поні-ферма"))
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=_disabled_settings(),
    )

    inspection, result = _inspect_and_answer(pipeline, "які є спорт активності")

    assert retriever.calls == []
    assert inspection.route_context.intent == "unknown"
    assert inspection.route_context.scope_detection.primary_scope == "park_activities"
    assert inspection.route_context.strategy == "overview_summary"
    rendered = render_query_answer(result)
    assert "- Ігрова зона" in rendered
    assert "- Поні-ферма" in rendered


def test_pipeline_existence_query_still_uses_retrieval_for_no_info(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest(tmp_path)
    retriever = FakeRetriever(
        SearchResponse(
            results=[],
            top_score=None,
            used_threshold=0.7,
            fallback_triggered=False,
            fallback_message=None,
        )
    )
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=_disabled_settings(),
    )

    inspection, result = _inspect_and_answer(pipeline, "Чи є у вас ковзани?")

    assert len(retriever.calls) == 1
    assert inspection.route_context.intent == "detail"
    assert inspection.route_context.strategy == "detail_retrieval"
    assert result.answer_text == NO_RELEVANT_INFO_FALLBACK
    assert result.source_section_ids == ()


def test_pipeline_detail_uses_retrieval_and_renders_nearby_sections(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    retriever = FakeRetriever(_search_response(logical_id="park", text="Поні-ферма"))
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=_disabled_settings(),
    )

    inspection, result = _inspect_and_answer(
        pipeline,
        "Чи є у вас поні-ферма?",
    )

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
    assert inspection.route_context.intent == "detail"
    assert inspection.route_context.strategy == "detail_retrieval"
    assert inspection.route_context.policy_trace.mode == "disabled"
    rendered = render_query_answer(result)
    assert "Знайшов найближчі розділи:" in rendered
    assert "Сімейний відпочинок > Що входить у вартість квитка?" in rendered
    assert "- Поні-ферма" in rendered


def test_pipeline_ambiguous_zoo_query_uses_deterministic_retrieval_rewrite(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    retriever = MappingRetriever(
        {
            "екскурсія на поні-ферму тварини ранчо": _search_response_with_score(
                logical_id="park",
                text="Поні-ферма\nЗнайомство з тваринами на ранчо.",
                score=0.93,
            )
        }
    )
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=_disabled_settings(),
    )

    inspection, result = _inspect_and_answer(
        pipeline,
        "хто у вас є в зоопарку?",
    )

    assert retriever.calls == [
        {
            "query": "екскурсія на поні-ферму тварини ранчо",
            "max_num_results": None,
            "rewrite_query": False,
            "score_threshold": None,
            "category": None,
            "logical_id": None,
            "attribute_filters": None,
        }
    ]
    assert (
        inspection.route_context.retrieval_plan.primary_query
        == "екскурсія на поні-ферму тварини ранчо"
    )
    assert inspection.retrieval_trace is not None
    assert inspection.retrieval_trace.stop_reason == "no_alternate_queries_planned"
    rendered = render_query_answer(result)
    assert "найближчі розділи" in rendered.casefold()
    assert "- Поні-ферма" in rendered


def test_pipeline_fallback_mode_keeps_strong_schedule_hit_without_llm_retry(
    tmp_path: Path,
) -> None:
    manifest_path = _write_schedule_manifest(tmp_path)
    retriever = FakeRetriever(
        _search_response_with_score(
            logical_id="schedule",
            text=(
                "# Св (Квітень Травень)\n\n"
                "📅 Графік роботи:\n"
                "• Парк працює по суботах та неділях\n"
                "• Час роботи: з 10:00 до 19:00\n"
            ),
            score=0.92,
        )
    )
    interpreter = FakeLLMInterpreter(
        QueryInterpretationResult(
            intent="detail",
            scope="park_activities",
            strategy="detail_retrieval",
            confidence=0.94,
            retrieval_hints=QueryRetrievalHints(
                primary_query="графік роботи Berry Land",
                alternate_queries=(),
                keywords=("графік роботи", "час роботи"),
                confidence=0.9,
            ),
        )
    )
    settings = KnowledgeBaseQuerySettings(
        _env_file=None,
        kb_query_llm_mode="fallback",
        kb_query_llm_allowed_for=("classifier", "scope", "planner", "retrieval"),
        kb_query_rules_min_confidence=0.85,
        kb_query_enable_stage_rules=True,
        kb_query_enable_stage_scope=True,
        kb_query_enable_stage_planner=True,
        kb_query_enable_stage_retrieval=True,
        kb_query_enable_stage_renderer=True,
        kb_query_llm_model=None,
        kb_query_llm_timeout_seconds=10,
        kb_query_llm_cache_size=32,
        kb_query_llm_max_retrieval_variants=1,
        openai_api_key=None,
    )
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=settings,
        llm_interpreter=interpreter,
    )

    inspection, result = _inspect_and_answer(
        pipeline,
        "Коли відкривається парк?",
    )

    assert len(interpreter.calls) == 0
    assert len(retriever.calls) == 1
    assert retriever.calls[0]["query"] == "Коли відкривається парк?"
    assert inspection.retrieval_trace is not None
    assert inspection.retrieval_trace.llm_escalation_triggered is False
    assert inspection.retrieval_trace.retry_executed is False
    assert inspection.retrieval_trace.renderer_trusted_top_hit is True
    rendered = render_query_answer(result)
    assert "Св (Квітень Травень)" in rendered
    assert "Час роботи: з 10:00 до 19:00" in rendered
    assert "Додаткові послуги на території парку" not in rendered.split("\n\n")[1]


def test_pipeline_animal_query_prefers_animal_lines_over_generic_program_content(
    tmp_path: Path,
) -> None:
    manifest_path = _write_animals_manifest(tmp_path)
    retriever = FakeRetriever(
        _search_response_with_score(
            logical_id="animals",
            text=(
                "# Парк пригод\n\n"
                "## Випускний Level 4.0\n\n"
                "• Вхід на територію\n"
                "• Водні розваги\n"
                "• Екскурсія на поні-ферму\n"
            ),
            score=0.83,
        )
    )
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=_disabled_settings(),
    )

    inspection, result = _inspect_and_answer(
        pipeline,
        "Які є у вас тваринки?",
    )

    assert inspection.retrieval_trace is not None
    rendered = render_query_answer(result)
    assert "козликами" in rendered
    assert "альпакою" in rendered
    assert "Водні розваги" not in rendered


def test_pipeline_safe_fallback_uses_search_fallback_when_structure_missing(tmp_path: Path) -> None:
    manifest_path = tmp_path / "missing.json"
    fallback_response = SearchResponse(
        results=[],
        top_score=None,
        used_threshold=0.7,
        fallback_triggered=True,
        fallback_message=NO_RELEVANT_INFO_FALLBACK,
    )
    retriever = FakeRetriever(fallback_response)
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=_disabled_settings(),
    )

    _, result = _inspect_and_answer(pipeline, "Незрозумілий запит")

    assert result.state == "fallback"
    assert render_query_answer(result) == NO_RELEVANT_INFO_FALLBACK


def test_pipeline_detail_falls_back_to_raw_hits_when_structure_missing(tmp_path: Path) -> None:
    manifest_path = tmp_path / "missing.json"
    retriever = FakeRetriever(
        _search_response(
            logical_id="park",
            text="✔ Поні-ферма\nЗнайомство з тваринами та екскурсія.",
        )
    )
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=_disabled_settings(),
    )

    _, result = _inspect_and_answer(pipeline, "Чи є у вас поні ферма?")

    assert result.state == "fallback"
    rendered = render_query_answer(result)
    assert NO_RELEVANT_INFO_FALLBACK not in rendered
    assert "сирі збіги" in rendered.casefold()
    assert "- Поні-ферма" in rendered
    assert "Sources:\n- park" in rendered


def test_pipeline_fallback_mode_escalates_once_for_weak_detail_result(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest(tmp_path)
    retriever = MappingRetriever(
        {
            "де можна побачити звірят?": SearchResponse(
                results=[],
                top_score=None,
                used_threshold=0.7,
                fallback_triggered=False,
                fallback_message=None,
            ),
            "екскурсія на поні-ферму тварини ранчо": _search_response_with_score(
                logical_id="park",
                text="Поні-ферма\nЗнайомство з тваринами на ранчо.",
                score=0.91,
            ),
        }
    )
    interpreter = FakeLLMInterpreter(
        QueryInterpretationResult(
            intent="detail",
            scope="park_activities",
            strategy="detail_retrieval",
            confidence=0.9,
            debug_note="Raw wording is weak; retry with Berry Land farm wording.",
            retrieval_hints=QueryRetrievalHints(
                primary_query="екскурсія на поні-ферму тварини ранчо",
                alternate_queries=("ферма до тваринок Berry Land",),
                keywords=("поні-ферма", "тварини"),
                confidence=0.87,
            ),
        )
    )
    settings = KnowledgeBaseQuerySettings(
        _env_file=None,
        kb_query_llm_mode="fallback",
        kb_query_llm_allowed_for=("classifier", "scope", "planner", "retrieval"),
        kb_query_rules_min_confidence=0.85,
        kb_query_enable_stage_rules=True,
        kb_query_enable_stage_scope=True,
        kb_query_enable_stage_planner=True,
        kb_query_enable_stage_retrieval=True,
        kb_query_enable_stage_renderer=True,
        kb_query_llm_model=None,
        kb_query_llm_timeout_seconds=10,
        kb_query_llm_cache_size=32,
        kb_query_llm_max_retrieval_variants=1,
        openai_api_key=None,
    )
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=settings,
        llm_interpreter=interpreter,
    )

    inspection, result = _inspect_and_answer(
        pipeline,
        "де можна побачити звірят?",
    )

    assert len(interpreter.calls) == 1
    assert [call["query"] for call in retriever.calls] == [
        "де можна побачити звірят?",
        "екскурсія на поні-ферму тварини ранчо",
    ]
    assert inspection.route_context.intent == "detail"
    assert inspection.route_context.scope_detection.primary_scope == "park_activities"
    assert (
        inspection.route_context.retrieval_plan.primary_query
        == "екскурсія на поні-ферму тварини ранчо"
    )
    assert inspection.retrieval_trace is not None
    assert inspection.retrieval_trace.llm_escalation_triggered is True
    assert inspection.retrieval_trace.llm_escalation_reason == "no_search_hits"
    assert inspection.retrieval_trace.retry_executed is True
    assert inspection.retrieval_trace.initial_executed_queries == ("де можна побачити звірят?",)
    assert inspection.retrieval_trace.executed_queries == ("екскурсія на поні-ферму тварини ранчо",)
    rendered = render_query_answer(result)
    assert "- Поні-ферма" in rendered


def test_pipeline_returns_no_relevant_info_for_unsupported_pricing_topic(
    tmp_path: Path,
) -> None:
    manifest_path = _write_services_manifest(tmp_path)
    retriever = FakeRetriever(
        SearchResponse(
            results=[
                SearchHit(
                    file_id="file_services",
                    filename="services.md",
                    score=0.78,
                    attributes={"logical_id": "services", "category": "services"},
                    text=(
                        "### Активності на воді\n"
                        "• Катання на катамаранах — 150 грн\n"
                        "• Катання на байдарках — 100 грн\n"
                    ),
                ),
                SearchHit(
                    file_id="file_services_2",
                    filename="services.md",
                    score=0.74,
                    attributes={"logical_id": "services", "category": "services"},
                    text=(
                        "### Оренда та послуги\n"
                        "• Велика альтанка — 2500 грн\n"
                        "• Трансфер — 4000 грн\n"
                    ),
                ),
            ],
            top_score=0.78,
            used_threshold=0.7,
            fallback_triggered=False,
            fallback_message=None,
        )
    )
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=_disabled_settings(),
    )

    inspection, result = _inspect_and_answer(
        pipeline,
        "Скільки коштує катання на ковзанах?",
    )

    assert result.answer_text == NO_RELEVANT_INFO_FALLBACK
    assert result.source_section_ids == ()
    assert inspection.retrieval_trace is not None
    assert inspection.retrieval_trace.renderer_trusted_top_hit is False
    assert inspection.retrieval_trace.renderer_note == "no_specific_query_evidence_in_hits"


def test_pipeline_forced_mode_still_rejects_unsupported_pricing_topic(
    tmp_path: Path,
) -> None:
    manifest_path = _write_services_manifest(tmp_path)
    retriever = FakeRetriever(
        SearchResponse(
            results=[
                SearchHit(
                    file_id="file_services",
                    filename="services.md",
                    score=0.82,
                    attributes={"logical_id": "services", "category": "services"},
                    text=(
                        "### Активності на воді\n"
                        "• Катання на катамаранах — 150 грн\n"
                        "• Катання на байдарках — 100 грн\n"
                    ),
                )
            ],
            top_score=0.82,
            used_threshold=0.7,
            fallback_triggered=False,
            fallback_message=None,
        )
    )
    interpreter = FakeLLMInterpreter(
        QueryInterpretationResult(
            intent="detail",
            scope="pricing",
            strategy="detail_retrieval",
            confidence=0.93,
            retrieval_hints=QueryRetrievalHints(
                primary_query="катання на ковзанах вартість",
                alternate_queries=("ковзани ціна",),
                keywords=("ковзани", "вартість", "ціна"),
                confidence=0.89,
            ),
        )
    )
    settings = KnowledgeBaseQuerySettings(
        _env_file=None,
        kb_query_llm_mode="forced",
        kb_query_llm_allowed_for=("classifier", "scope", "planner", "retrieval"),
        kb_query_rules_min_confidence=0.85,
        kb_query_enable_stage_rules=True,
        kb_query_enable_stage_scope=True,
        kb_query_enable_stage_planner=True,
        kb_query_enable_stage_retrieval=True,
        kb_query_enable_stage_renderer=True,
        kb_query_llm_model=None,
        kb_query_llm_timeout_seconds=10,
        kb_query_llm_cache_size=32,
        kb_query_llm_max_retrieval_variants=0,
        openai_api_key=None,
    )
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=settings,
        llm_interpreter=interpreter,
    )

    inspection, result = _inspect_and_answer(
        pipeline,
        "Скільки коштує катання на ковзанах?",
    )

    assert result.answer_text == NO_RELEVANT_INFO_FALLBACK
    assert result.source_section_ids == ()
    assert inspection.retrieval_trace is not None
    assert inspection.retrieval_trace.renderer_note == "no_specific_query_evidence_in_hits"


def test_pipeline_llm_retrieval_plan_tries_alternate_when_primary_is_weak(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest(tmp_path)
    retriever = MappingRetriever(
        {
            "тварини Berry Land": _search_response_with_score(
                logical_id="programs",
                text="Програма А",
                score=0.54,
            ),
            "екскурсія на поні-ферму тварини ранчо": _search_response_with_score(
                logical_id="park",
                text="Поні-ферма\nЗнайомство з тваринами на ранчо.",
                score=0.84,
            ),
        }
    )
    interpreter = FakeLLMInterpreter(
        QueryInterpretationResult(
            intent="detail",
            scope="park_activities",
            strategy="detail_retrieval",
            confidence=0.93,
            retrieval_hints=QueryRetrievalHints(
                primary_query="тварини Berry Land",
                alternate_queries=("екскурсія на поні-ферму тварини ранчо",),
                keywords=("поні-ферма", "тварини", "ранчо"),
                confidence=0.92,
            ),
        )
    )
    settings = KnowledgeBaseQuerySettings(
        _env_file=None,
        kb_query_llm_mode="forced",
        kb_query_llm_allowed_for=("classifier", "scope", "planner", "retrieval"),
        kb_query_rules_min_confidence=0.85,
        kb_query_enable_stage_rules=True,
        kb_query_enable_stage_scope=True,
        kb_query_enable_stage_planner=True,
        kb_query_enable_stage_retrieval=True,
        kb_query_enable_stage_renderer=True,
        kb_query_llm_model=None,
        kb_query_llm_timeout_seconds=10,
        kb_query_llm_cache_size=32,
        kb_query_llm_max_retrieval_variants=1,
        openai_api_key=None,
    )
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=settings,
        llm_interpreter=interpreter,
    )

    inspection, result = _inspect_and_answer(
        pipeline,
        "хто у вас є в зоопарку?",
    )

    assert [call["query"] for call in retriever.calls] == [
        "тварини Berry Land",
        "екскурсія на поні-ферму тварини ранчо",
    ]
    assert inspection.retrieval_trace is not None
    assert inspection.retrieval_trace.stop_reason == "planned_queries_exhausted"
    rendered = render_query_answer(result)
    assert "- Поні-ферма" in rendered


def test_pipeline_stops_after_primary_when_retrieval_is_strong(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    retriever = MappingRetriever(
        {
            "екскурсія на поні-ферму тварини ранчо": _search_response_with_score(
                logical_id="park",
                text="Поні-ферма\nЗнайомство з тваринами на ранчо.",
                score=0.93,
            ),
            "ферма до тваринок Berry Land": _search_response_with_score(
                logical_id="park",
                text="Поні-ферма",
                score=0.86,
            ),
        }
    )
    interpreter = FakeLLMInterpreter(
        QueryInterpretationResult(
            intent="detail",
            scope="park_activities",
            strategy="detail_retrieval",
            confidence=0.93,
            retrieval_hints=QueryRetrievalHints(
                primary_query="екскурсія на поні-ферму тварини ранчо",
                alternate_queries=("ферма до тваринок Berry Land",),
                keywords=("поні-ферма", "тварини", "ранчо"),
                confidence=0.92,
            ),
        )
    )
    settings = KnowledgeBaseQuerySettings(
        _env_file=None,
        kb_query_llm_mode="forced",
        kb_query_llm_allowed_for=("classifier", "scope", "planner", "retrieval"),
        kb_query_rules_min_confidence=0.85,
        kb_query_enable_stage_rules=True,
        kb_query_enable_stage_scope=True,
        kb_query_enable_stage_planner=True,
        kb_query_enable_stage_retrieval=True,
        kb_query_enable_stage_renderer=True,
        kb_query_llm_model=None,
        kb_query_llm_timeout_seconds=10,
        kb_query_llm_cache_size=32,
        kb_query_llm_max_retrieval_variants=1,
        openai_api_key=None,
    )
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        policy_settings=settings,
        llm_interpreter=interpreter,
    )

    inspection, _result = _inspect_and_answer(
        pipeline,
        "хто у вас є в зоопарку?",
    )

    assert [call["query"] for call in retriever.calls] == [
        "екскурсія на поні-ферму тварини ранчо",
    ]
    assert inspection.retrieval_trace is not None
    assert inspection.retrieval_trace.stop_reason == "primary_top_score_sufficient"


def test_execute_query_plan_broadens_scope_for_low_confidence_scope_detection() -> None:
    document = StructuredDocument(
        logical_id="services",
        title="Services",
        category="services",
        source_file="kb.xlsx",
        markdown_path=Path("services.md"),
        scopes=("services",),
        sections=(
            StructuredSection(
                heading="Додаткові послуги",
                level=2,
                heading_path=("Services", "Додаткові послуги"),
                body="- Альтанки\n- Кафе та бар",
            ),
        ),
    )
    reader = StaticStructureReader(scoped_documents=(), all_documents=(document,))
    route_context = QueryRouteContext(
        classification=QueryClassification(
            intent="overview",
            confidence=0.92,
            source="rules",
        ),
        scope_detection=QueryScopeDetection(
            primary_scope="services",
            scopes=("services",),
            confidence=0.2,
            source="rules",
        ),
        strategy="overview_summary",
        retrieval_plan=QueryRetrievalPlan(primary_query="що у вас є"),
        needs_retrieval=False,
        needs_structure=True,
        strategy_source="rules",
        policy_trace=QueryPolicyTrace(rules_min_confidence=0.85),
    )

    result = execute_query_plan(
        "Що у вас є?",
        route_context,
        structure_reader=reader,
    )

    assert result.state == "answered"
    assert result.source_section_ids
    assert "Додаткові послуги" in render_query_answer(result)


def test_execute_query_plan_keeps_scope_strict_when_confidence_is_high() -> None:
    document = StructuredDocument(
        logical_id="services",
        title="Services",
        category="services",
        source_file="kb.xlsx",
        markdown_path=Path("services.md"),
        scopes=("services",),
        sections=(
            StructuredSection(
                heading="Додаткові послуги",
                level=2,
                heading_path=("Services", "Додаткові послуги"),
                body="- Альтанки\n- Кафе та бар",
            ),
        ),
    )
    reader = StaticStructureReader(scoped_documents=(), all_documents=(document,))
    route_context = QueryRouteContext(
        classification=QueryClassification(
            intent="overview",
            confidence=0.92,
            source="rules",
        ),
        scope_detection=QueryScopeDetection(
            primary_scope="services",
            scopes=("services",),
            confidence=0.95,
            source="rules",
        ),
        strategy="overview_summary",
        retrieval_plan=QueryRetrievalPlan(primary_query="що у вас є"),
        needs_retrieval=False,
        needs_structure=True,
        strategy_source="rules",
        policy_trace=QueryPolicyTrace(rules_min_confidence=0.85),
    )

    result = execute_query_plan(
        "Що у вас є?",
        route_context,
        structure_reader=reader,
    )

    assert result.state == "fallback"
    assert result.source_section_ids == ()
    assert result.answer_text == NO_RELEVANT_INFO_FALLBACK
