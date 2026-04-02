from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.services.knowledge_base.types_openai import SearchResponse

QueryIntent = Literal["detail", "enumeration", "overview", "comparison", "unknown"]
QueryScopeName = Literal[
    "programs",
    "services",
    "park_activities",
    "food",
    "zones",
    "pricing",
    "transfer",
    "general",
]
QueryStrategy = Literal[
    "detail_retrieval",
    "enumeration_catalog",
    "overview_summary",
    "comparison_summary",
    "safe_fallback",
]


@dataclass(frozen=True, slots=True)
class RuleMatch:
    rule_id: str
    priority: int
    description: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QueryClassification:
    intent: QueryIntent
    confidence: float
    matched_rules: tuple[RuleMatch, ...] = ()
    rationale: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QueryScopeDetection:
    primary_scope: QueryScopeName
    scopes: tuple[QueryScopeName, ...]
    confidence: float
    matched_rules: tuple[RuleMatch, ...] = ()
    rationale: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QueryPlan:
    classification: QueryClassification
    scope_detection: QueryScopeDetection
    strategy: QueryStrategy
    needs_retrieval: bool
    needs_structure: bool
    rationale: tuple[str, ...] = ()

    @property
    def intent(self) -> QueryIntent:
        return self.classification.intent


@dataclass(frozen=True, slots=True)
class AnswerBlock:
    title: str
    lines: tuple[str, ...] = ()
    body: str | None = None


@dataclass(frozen=True, slots=True)
class QueryAnswerResult:
    plan: QueryPlan
    blocks: tuple[AnswerBlock, ...]
    summary: str | None
    sources: tuple[str, ...] = ()
    search_response: SearchResponse | None = None
    fallback_used: bool = False


@dataclass(frozen=True, slots=True)
class StructuredSection:
    heading: str
    level: int
    heading_path: tuple[str, ...]
    body: str


@dataclass(frozen=True, slots=True)
class StructuredDocument:
    logical_id: str
    title: str
    category: str
    source_file: str
    markdown_path: Path
    scopes: tuple[QueryScopeName, ...]
    sections: tuple[StructuredSection, ...]


@dataclass(frozen=True, slots=True)
class SearchHitDebugContext:
    logical_id: str
    source_file: str | None
    document_title: str | None
    heading_path: tuple[str, ...] = field(default_factory=tuple)
