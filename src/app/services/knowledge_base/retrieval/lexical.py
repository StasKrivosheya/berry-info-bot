from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.services.knowledge_base.retrieval.candidates import (
    KnowledgeBaseCandidate,
    build_candidates_from_manifest,
)

DEFAULT_LEXICAL_INDEX_PATH = Path("data/knowledge_base/processed/kb_lexical.sqlite3")
DEFAULT_LEXICAL_MAX_RESULTS = 10
LOG_EVENT_LEXICAL_INDEX_REBUILT = "kb_lexical_index_rebuilt"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LexicalSearchHit:
    candidate: KnowledgeBaseCandidate
    score: float


@dataclass(frozen=True, slots=True)
class LexicalIndexBuildReport:
    index_path: Path
    candidate_count: int


class SQLiteLexicalIndex:
    """Local SQLite FTS5 index for processed knowledge-base sections."""

    def __init__(self, index_path: Path | None = None) -> None:
        self._index_path = (index_path or default_lexical_index_path()).resolve()

    @property
    def index_path(self) -> Path:
        return self._index_path

    def rebuild(self, candidates: tuple[KnowledgeBaseCandidate, ...]) -> LexicalIndexBuildReport:
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._index_path) as connection:
            _create_schema(connection)
            connection.execute("DELETE FROM kb_fts")
            connection.executemany(
                """
                INSERT INTO kb_fts (
                    candidate_id,
                    logical_id,
                    section_id,
                    category,
                    source_category,
                    direction_id,
                    topic_ids,
                    period_label,
                    heading_path,
                    content,
                    source_file,
                    source_format,
                    sheet_name,
                    sheet_index,
                    workbook_file,
                    markdown_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [_candidate_row(candidate) for candidate in candidates],
            )
            connection.commit()

        logger.info(
            "%s index=%s candidate_count=%s",
            LOG_EVENT_LEXICAL_INDEX_REBUILT,
            self._index_path.as_posix(),
            len(candidates),
        )
        return LexicalIndexBuildReport(
            index_path=self._index_path,
            candidate_count=len(candidates),
        )

    def search(
        self,
        *,
        keywords: tuple[str, ...] = (),
        phrases: tuple[str, ...] = (),
        query: str | None = None,
        max_results: int = DEFAULT_LEXICAL_MAX_RESULTS,
        category_hint: str | None = None,
        logical_id_hint: str | None = None,
    ) -> tuple[LexicalSearchHit, ...]:
        match_query = build_fts_query(keywords=keywords, phrases=phrases, query=query)
        if not match_query or not self._index_path.exists():
            return ()

        clauses = ["kb_fts MATCH ?"]
        params: list[object] = [match_query]
        if category_hint:
            clauses.append("category = ?")
            params.append(category_hint)
        if logical_id_hint:
            clauses.append("logical_id = ?")
            params.append(logical_id_hint)
        params.append(max(1, max_results))

        with sqlite3.connect(self._index_path) as connection:
            connection.row_factory = sqlite3.Row
            sql = _build_search_sql(
                clauses=clauses,
                columns=_table_columns(connection),
            )
            rows = connection.execute(sql, params).fetchall()

        return tuple(_hit_from_row(row) for row in rows)


def build_lexical_index_from_manifest(
    manifest_path: Path,
    *,
    index_path: Path | None = None,
) -> LexicalIndexBuildReport:
    candidates = build_candidates_from_manifest(manifest_path)
    return SQLiteLexicalIndex(index_path).rebuild(candidates)


def default_lexical_index_path() -> Path:
    configured = os.getenv("KB_LEXICAL_INDEX_PATH", "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_LEXICAL_INDEX_PATH


def build_fts_query(
    *,
    keywords: tuple[str, ...] = (),
    phrases: tuple[str, ...] = (),
    query: str | None = None,
) -> str:
    terms: list[str] = []
    for value in (*phrases, *keywords):
        normalized = " ".join(str(value).strip().split())
        if normalized:
            terms.append(_quote_fts_phrase(normalized))
    if not terms and query:
        normalized_query = " ".join(query.strip().split())
        if normalized_query:
            terms.append(_quote_fts_phrase(normalized_query))
    return " OR ".join(dict.fromkeys(terms))


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS kb_fts")
    connection.execute(
        """
        CREATE VIRTUAL TABLE kb_fts USING fts5(
            candidate_id UNINDEXED,
            logical_id UNINDEXED,
            section_id UNINDEXED,
            category UNINDEXED,
            source_category UNINDEXED,
            direction_id UNINDEXED,
            topic_ids UNINDEXED,
            period_label UNINDEXED,
            heading_path UNINDEXED,
            content,
            source_file UNINDEXED,
            source_format UNINDEXED,
            sheet_name UNINDEXED,
            sheet_index UNINDEXED,
            workbook_file UNINDEXED,
            markdown_path UNINDEXED,
            tokenize='unicode61'
        )
        """
    )


def _candidate_row(candidate: KnowledgeBaseCandidate) -> tuple[object, ...]:
    return (
        candidate.candidate_id,
        candidate.logical_id,
        candidate.section_id,
        candidate.category,
        candidate.source_category,
        candidate.direction_id,
        ",".join(candidate.topic_ids),
        candidate.period_label,
        json.dumps(list(candidate.heading_path), ensure_ascii=False),
        candidate.content,
        candidate.source_file,
        candidate.source_format,
        candidate.sheet_name,
        candidate.sheet_index,
        candidate.workbook_file,
        candidate.markdown_path,
    )


def _hit_from_row(row: sqlite3.Row) -> LexicalSearchHit:
    rank = float(row["rank"])
    return LexicalSearchHit(
        candidate=KnowledgeBaseCandidate(
            candidate_id=str(row["candidate_id"]),
            logical_id=str(row["logical_id"]),
            section_id=str(row["section_id"]),
            category=str(row["category"]),
            source_category=str(row["source_category"] or row["category"]),
            direction_id=str(row["direction_id"]) if row["direction_id"] else None,
            topic_ids=_split_csv_tuple(row["topic_ids"]),
            period_label=str(row["period_label"]) if row["period_label"] else None,
            heading_path=tuple(json.loads(str(row["heading_path"] or "[]"))),
            content=str(row["content"]),
            source_file=str(row["source_file"]),
            source_format=str(row["source_format"]),
            sheet_name=str(row["sheet_name"]) if row["sheet_name"] is not None else None,
            sheet_index=int(row["sheet_index"]) if row["sheet_index"] is not None else None,
            workbook_file=(
                str(row["workbook_file"]) if row["workbook_file"] is not None else None
            ),
            markdown_path=str(row["markdown_path"]),
        ),
        score=max(0.0, -rank),
    )


def _quote_fts_phrase(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _build_search_sql(
    *,
    clauses: list[str],
    columns: set[str],
) -> str:
    select_columns = [
        "candidate_id",
        "logical_id",
        "section_id",
        "category",
        _select_column(columns, "source_category", "category"),
        _select_column(columns, "direction_id", "NULL"),
        _select_column(columns, "topic_ids", "''"),
        _select_column(columns, "period_label", "NULL"),
        "heading_path",
        "content",
        "source_file",
        "source_format",
        "sheet_name",
        "sheet_index",
        "workbook_file",
        "markdown_path",
        "bm25(kb_fts) AS rank",
    ]
    return f"""
        SELECT
            {", ".join(select_columns)}
        FROM kb_fts
        WHERE {" AND ".join(clauses)}
        ORDER BY rank
        LIMIT ?
    """


def _select_column(columns: set[str], name: str, fallback: str) -> str:
    if name in columns:
        return name
    return f"{fallback} AS {name}"


def _table_columns(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("PRAGMA table_info(kb_fts)").fetchall()
    return {str(row[1]) for row in rows}


def _split_csv_tuple(value: object) -> tuple[str, ...]:
    raw = str(value or "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())
