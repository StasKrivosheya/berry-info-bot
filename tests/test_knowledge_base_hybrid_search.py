# ruff: noqa: RUF001

from __future__ import annotations

import json
from pathlib import Path

from app.services.knowledge_base.query.structure import KnowledgeBaseStructureReader
from app.services.knowledge_base.query_router import QueryRoute
from app.services.knowledge_base.retrieval.hybrid import HybridSearchService
from app.services.knowledge_base.retrieval.lexical import (
    SQLiteLexicalIndex,
    build_lexical_index_from_manifest,
)
from app.services.knowledge_base.types_openai import SearchHit, SearchResponse


class FakeVectorSearch:
    def __init__(self, response: SearchResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> SearchResponse:
        self.calls.append(kwargs)
        return self.response


def write_tiny_manifest(tmp_path: Path) -> Path:
    output_dir = tmp_path / "processed"
    markdown_dir = output_dir / "markdown"
    markdown_dir.mkdir(parents=True)
    (markdown_dir / "programs.md").write_text(
        "\n".join(
            (
                "# Організовані програми",
                "",
                "## Програма пригод",
                "Квест, поні-ферма та активності для дітей.",
                "",
                "## Трансфер",
                "Трансфер з Дніпра оплачується окремо.",
            )
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
                        "updated_at_utc": "2026-04-27T00:00:00+00:00",
                        "row_count": 5,
                        "non_empty_cell_count": 5,
                        "content_hash_sha256": "hash-programs",
                    }
                ],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def _route() -> QueryRoute:
    return QueryRoute(
        route="kb_query",
        original_message="Які активності є для дітей?",
        canonical_question_uk="Які активності для дітей є в Berry Land?",
        vector_query_uk="активності для дітей поні-ферма",
        lexical_keywords=["поні-ферма", "активності"],
        lexical_phrases=["активності для дітей"],
        confidence=0.94,
    )


def test_hybrid_search_merges_vector_and_lexical_and_deduplicates(tmp_path: Path) -> None:
    manifest_path = write_tiny_manifest(tmp_path)
    index_path = tmp_path / "kb.sqlite3"
    build_lexical_index_from_manifest(manifest_path, index_path=index_path)
    vector = FakeVectorSearch(
        SearchResponse(
            results=[
                SearchHit(
                    file_id="file_programs",
                    filename="programs.md",
                    score=0.86,
                    attributes={"logical_id": "programs", "category": "programs"},
                    text="Програма пригод\nКвест, поні-ферма та активності для дітей.",
                ),
                SearchHit(
                    file_id="file_contacts",
                    filename="contacts.md",
                    score=0.74,
                    attributes={"logical_id": "contacts", "category": "contacts"},
                    text="Телефон Berry Land.",
                ),
            ],
            top_score=0.86,
            used_threshold=0.7,
            fallback_triggered=False,
            fallback_message=None,
        )
    )
    service = HybridSearchService(
        vector_search=vector,
        lexical_index=SQLiteLexicalIndex(index_path),
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        max_candidates=8,
    )

    result = service.search(_route())

    assert vector.calls == [
        {
            "query": "активності для дітей поні-ферма",
            "max_num_results": None,
            "rewrite_query": False,
            "score_threshold": None,
            "category": None,
            "logical_id": None,
            "attribute_filters": None,
        }
    ]
    assert result.vector_result_count == 2
    assert result.lexical_result_count == 1
    assert len(result.candidates) == 2
    assert {candidate.source for candidate in result.candidates} == {"both", "vector"}
    both = next(candidate for candidate in result.candidates if candidate.source == "both")
    assert both.logical_id == "programs"
    assert both.vector_score == 0.86
    assert both.lexical_score is not None
    assert "Програма пригод" in both.heading_path


def test_hybrid_search_returns_lexical_only_candidates(tmp_path: Path) -> None:
    manifest_path = write_tiny_manifest(tmp_path)
    index_path = tmp_path / "kb.sqlite3"
    build_lexical_index_from_manifest(manifest_path, index_path=index_path)
    vector = FakeVectorSearch(
        SearchResponse(
            results=[],
            top_score=None,
            used_threshold=0.7,
            fallback_triggered=True,
            fallback_message=None,
        )
    )
    service = HybridSearchService(
        vector_search=vector,
        lexical_index=SQLiteLexicalIndex(index_path),
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        max_candidates=8,
    )

    result = service.search(_route())

    assert result.vector_result_count == 0
    assert result.lexical_result_count == 1
    assert len(result.candidates) == 1
    assert result.candidates[0].source == "lexical"


def test_hybrid_search_returns_empty_for_no_results(tmp_path: Path) -> None:
    manifest_path = write_tiny_manifest(tmp_path)
    index_path = tmp_path / "kb.sqlite3"
    build_lexical_index_from_manifest(manifest_path, index_path=index_path)
    vector = FakeVectorSearch(
        SearchResponse(
            results=[],
            top_score=None,
            used_threshold=0.7,
            fallback_triggered=True,
            fallback_message=None,
        )
    )
    route = QueryRoute(
        route="kb_query",
        original_message="Чи є аквапарк?",
        canonical_question_uk="Чи є аквапарк у Berry Land?",
        vector_query_uk="аквапарк Berry Land",
        lexical_keywords=["аквапарк"],
        lexical_phrases=["аквапарк Berry Land"],
        confidence=0.8,
    )
    service = HybridSearchService(
        vector_search=vector,
        lexical_index=SQLiteLexicalIndex(index_path),
        structure_reader=KnowledgeBaseStructureReader(manifest_path),
        max_candidates=8,
    )

    result = service.search(route)

    assert result.candidates == ()
    assert result.vector_result_count == 0
    assert result.lexical_result_count == 0
