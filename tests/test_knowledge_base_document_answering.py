# ruff: noqa: RUF001

from __future__ import annotations

import json
from pathlib import Path

from app.services.knowledge_base.query_classifier import classify_query_intent
from app.services.knowledge_base.query_pipeline import KnowledgeBaseQueryPipeline
from app.services.knowledge_base.query_planner import build_query_plan
from app.services.knowledge_base.query_renderer import render_query_answer
from app.services.knowledge_base.query_scope import detect_query_scope
from app.services.knowledge_base.structure_reader import KnowledgeBaseStructureReader
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
            "## ДОДАТКОВІ ПОСЛУГИ\n"
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

    plan = build_query_plan(classification, scope_detection)

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
    )

    result = pipeline.answer_query("Які є види організованих програм?")

    assert retriever.calls == []
    assert result.plan.intent == "enumeration"
    assert result.plan.strategy == "enumeration_catalog"
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
    )

    result = pipeline.answer_query("Що ви можете мені запропонувати?")

    assert retriever.calls == []
    assert result.plan.intent == "overview"
    assert result.plan.strategy == "overview_summary"
    rendered = render_query_answer(result)
    assert "Організовані програми" in rendered
    assert "У парку можна" in rendered
    assert "- Ігрова зона" in rendered
    assert "- Поні-ферма" in rendered
    assert "Додаткові послуги" in rendered
    assert "- Альтанки з мангалом" in rendered


def test_pipeline_detail_uses_retrieval_and_renders_nearby_sections(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    retriever = FakeRetriever(_search_response(logical_id="park", text="Поні-ферма"))
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
    )

    result = pipeline.answer_query("Чи є у вас поні-ферма?")

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
    assert result.plan.intent == "detail"
    assert result.plan.strategy == "detail_retrieval"
    rendered = render_query_answer(result)
    assert "Знайшов найближчі розділи:" in rendered
    assert "Сімейний відпочинок > Що входить у вартість квитка?" in rendered
    assert "- Поні-ферма" in rendered


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
    )

    result = pipeline.answer_query("Незрозумілий запит")

    assert result.fallback_used is True
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
    )

    result = pipeline.answer_query("Чи є у вас поні ферма?")

    assert result.fallback_used is True
    rendered = render_query_answer(result)
    assert NO_RELEVANT_INFO_FALLBACK not in rendered
    assert "сирі збіги" in rendered.casefold()
    assert "- Поні-ферма" in rendered
    assert "Sources:\n- park" in rendered
