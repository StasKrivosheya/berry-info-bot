from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.services.knowledge_base.query.structure import KnowledgeBaseStructureReader
from app.services.knowledge_base.query_router import QueryRoute
from app.services.knowledge_base.retrieval.candidates import (
    KnowledgeBaseCandidate,
    stable_section_id,
)
from app.services.knowledge_base.retrieval.lexical import (
    DEFAULT_LEXICAL_MAX_RESULTS,
    LexicalSearchHit,
    SQLiteLexicalIndex,
)
from app.services.knowledge_base.retrieval.service import KnowledgeBaseRetrievalService
from app.services.knowledge_base.types_openai import SearchHit, SearchResponse

HybridSource = Literal["vector", "lexical", "both"]
DEFAULT_HYBRID_MAX_CANDIDATES = 10

logger = logging.getLogger(__name__)


class VectorSearchService(Protocol):
    def search(self, **kwargs: object) -> SearchResponse:
        """Return normalized vector-store search response."""


@dataclass(frozen=True, slots=True)
class HybridCandidate:
    candidate_id: str
    logical_id: str
    section_id: str
    category: str
    heading_path: tuple[str, ...]
    content: str
    source: HybridSource
    score: float
    vector_score: float | None
    lexical_score: float | None
    source_file: str | None = None
    markdown_path: str | None = None


@dataclass(frozen=True, slots=True)
class HybridSearchResult:
    candidates: tuple[HybridCandidate, ...]
    vector_result_count: int
    lexical_result_count: int


class HybridSearchService:
    """Run vector + SQLite lexical retrieval and return deduplicated candidates."""

    def __init__(
        self,
        *,
        vector_search: VectorSearchService | None = None,
        lexical_index: SQLiteLexicalIndex | None = None,
        structure_reader: KnowledgeBaseStructureReader | None = None,
        max_candidates: int = DEFAULT_HYBRID_MAX_CANDIDATES,
    ) -> None:
        self._vector_search = vector_search or KnowledgeBaseRetrievalService()
        self._lexical_index = lexical_index or SQLiteLexicalIndex()
        self._structure_reader = structure_reader or KnowledgeBaseStructureReader()
        self._max_candidates = max(1, max_candidates)

    def search(self, route: QueryRoute) -> HybridSearchResult:
        if route.route not in {"kb_query", "follow_up"} or not route.vector_query_uk:
            return HybridSearchResult(
                candidates=(),
                vector_result_count=0,
                lexical_result_count=0,
            )

        vector_response = self._vector_search.search(
            query=route.vector_query_uk,
            max_num_results=None,
            rewrite_query=False,
            score_threshold=None,
            category=route.category_hint,
            logical_id=route.logical_id_hint,
            attribute_filters=None,
        )
        lexical_hits = self._lexical_index.search(
            keywords=tuple(route.lexical_keywords),
            phrases=tuple(route.lexical_phrases),
            query=route.vector_query_uk,
            max_results=max(DEFAULT_LEXICAL_MAX_RESULTS, self._max_candidates),
            category_hint=route.category_hint,
            logical_id_hint=route.logical_id_hint,
        )
        candidates = merge_candidates(
            vector_hits=tuple(vector_response.results),
            lexical_hits=lexical_hits,
            structure_reader=self._structure_reader,
            max_candidates=self._max_candidates,
        )
        return HybridSearchResult(
            candidates=candidates,
            vector_result_count=len(vector_response.results),
            lexical_result_count=len(lexical_hits),
        )


def merge_candidates(
    *,
    vector_hits: tuple[SearchHit, ...],
    lexical_hits: tuple[LexicalSearchHit, ...],
    structure_reader: KnowledgeBaseStructureReader,
    max_candidates: int = DEFAULT_HYBRID_MAX_CANDIDATES,
) -> tuple[HybridCandidate, ...]:
    merged: dict[str, HybridCandidate] = {}

    for rank, hit in enumerate(vector_hits):
        candidate = _candidate_from_vector_hit(hit, structure_reader=structure_reader)
        weighted_score = _vector_rank_score(hit.score, rank)
        merged[candidate.candidate_id] = HybridCandidate(
            candidate_id=candidate.candidate_id,
            logical_id=candidate.logical_id,
            section_id=candidate.section_id,
            category=candidate.category,
            heading_path=candidate.heading_path,
            content=candidate.content,
            source="vector",
            score=weighted_score,
            vector_score=hit.score,
            lexical_score=None,
            source_file=candidate.source_file,
            markdown_path=candidate.markdown_path,
        )

    for rank, hit in enumerate(lexical_hits):
        lexical_score = _lexical_rank_score(hit.score, rank)
        existing = merged.get(hit.candidate.candidate_id)
        if existing is None:
            merged[hit.candidate.candidate_id] = _hybrid_from_lexical_hit(
                hit,
                lexical_score=lexical_score,
            )
            continue

        merged[hit.candidate.candidate_id] = HybridCandidate(
            candidate_id=existing.candidate_id,
            logical_id=existing.logical_id or hit.candidate.logical_id,
            section_id=existing.section_id or hit.candidate.section_id,
            category=existing.category or hit.candidate.category,
            heading_path=hit.candidate.heading_path or existing.heading_path,
            content=hit.candidate.content or existing.content,
            source="both",
            score=existing.score + lexical_score,
            vector_score=existing.vector_score,
            lexical_score=hit.score,
            source_file=hit.candidate.source_file or existing.source_file,
            markdown_path=hit.candidate.markdown_path or existing.markdown_path,
        )

    ranked = sorted(
        merged.values(),
        key=lambda candidate: (
            -candidate.score,
            candidate.source != "both",
            candidate.logical_id,
            candidate.section_id,
        ),
    )
    return tuple(ranked[: max(1, max_candidates)])


def _candidate_from_vector_hit(
    hit: SearchHit,
    *,
    structure_reader: KnowledgeBaseStructureReader,
) -> KnowledgeBaseCandidate:
    context = structure_reader.resolve_hit_context(hit)
    logical_id = str(hit.attributes.get("logical_id", "")).strip() or Path(hit.filename).stem
    category = str(hit.attributes.get("category", "")).strip()
    heading_path = context.heading_path if context is not None else ()
    if not heading_path:
        heading_path = (hit.filename,)
    section_id = stable_section_id(logical_id, heading_path)
    return KnowledgeBaseCandidate(
        candidate_id=section_id,
        logical_id=logical_id,
        section_id=section_id,
        category=category,
        heading_path=heading_path,
        content=hit.text,
        source_file=context.source_file if context is not None else "",
        source_format=str(hit.attributes.get("source_format", "")),
        sheet_name=(
            str(hit.attributes["sheet_name"])
            if hit.attributes.get("sheet_name") is not None
            else None
        ),
        sheet_index=(
            int(hit.attributes["sheet_index"])
            if hit.attributes.get("sheet_index") is not None
            else None
        ),
        workbook_file=(
            str(hit.attributes["workbook_file"])
            if hit.attributes.get("workbook_file") is not None
            else None
        ),
        markdown_path=hit.filename,
    )


def _hybrid_from_lexical_hit(
    hit: LexicalSearchHit,
    *,
    lexical_score: float,
) -> HybridCandidate:
    return HybridCandidate(
        candidate_id=hit.candidate.candidate_id,
        logical_id=hit.candidate.logical_id,
        section_id=hit.candidate.section_id,
        category=hit.candidate.category,
        heading_path=hit.candidate.heading_path,
        content=hit.candidate.content,
        source="lexical",
        score=lexical_score,
        vector_score=None,
        lexical_score=hit.score,
        source_file=hit.candidate.source_file,
        markdown_path=hit.candidate.markdown_path,
    )


def _vector_rank_score(score: float, rank: int) -> float:
    return max(0.0, score) + 1.0 / (rank + 1)


def _lexical_rank_score(score: float, rank: int) -> float:
    return max(0.0, score) + 1.0 / (rank + 1)
