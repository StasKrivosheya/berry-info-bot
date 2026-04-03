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
QueryDecisionSource = Literal["rules", "llm", "default"]
QueryLLMMode = Literal["disabled", "fallback", "forced"]
QueryInterpretationStage = Literal["classifier", "scope", "planner", "retrieval"]


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
    source: QueryDecisionSource = "rules"


@dataclass(frozen=True, slots=True)
class QueryScopeDetection:
    primary_scope: QueryScopeName
    scopes: tuple[QueryScopeName, ...]
    confidence: float
    matched_rules: tuple[RuleMatch, ...] = ()
    rationale: tuple[str, ...] = ()
    source: QueryDecisionSource = "rules"


@dataclass(frozen=True, slots=True)
class QueryRetrievalHints:
    primary_query: str
    alternate_queries: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    confidence: float = 0.0
    debug_note: str | None = None


@dataclass(frozen=True, slots=True)
class QueryRetrievalPlan:
    primary_query: str
    alternate_queries: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    confidence: float = 0.0
    source: QueryDecisionSource = "rules"
    rationale: tuple[str, ...] = ()
    debug_note: str | None = None

    @property
    def planned_queries(self) -> tuple[str, ...]:
        return tuple(
            query
            for query in (self.primary_query, *self.alternate_queries)
            if query
        )


@dataclass(frozen=True, slots=True)
class QueryStageToggles:
    rules_enabled: bool = True
    scope_enabled: bool = True
    planner_enabled: bool = True
    retrieval_enabled: bool = True
    renderer_enabled: bool = True


@dataclass(frozen=True, slots=True)
class QueryPolicyTrace:
    mode: QueryLLMMode = "disabled"
    llm_allowed_for: tuple[QueryInterpretationStage, ...] = ()
    stage_toggles: QueryStageToggles = field(default_factory=QueryStageToggles)
    rules_min_confidence: float = 0.0
    deterministic_classification: QueryClassification | None = None
    deterministic_scope_detection: QueryScopeDetection | None = None
    deterministic_strategy: QueryStrategy = "safe_fallback"
    deterministic_retrieval_plan: QueryRetrievalPlan | None = None
    final_intent_source: QueryDecisionSource = "default"
    final_scope_source: QueryDecisionSource = "default"
    final_strategy_source: QueryDecisionSource = "default"
    final_retrieval_source: QueryDecisionSource = "default"
    llm_requested: bool = False
    llm_used: bool = False
    llm_cache_hit: bool = False
    llm_stages_requested: tuple[QueryInterpretationStage, ...] = ()
    llm_skip_reason: str | None = None
    llm_failure_reason: str | None = None
    llm_debug_note: str | None = None


@dataclass(frozen=True, slots=True)
class QueryPlan:
    classification: QueryClassification
    scope_detection: QueryScopeDetection
    strategy: QueryStrategy
    retrieval_plan: QueryRetrievalPlan
    needs_retrieval: bool
    needs_structure: bool
    rationale: tuple[str, ...] = ()
    strategy_source: QueryDecisionSource = "rules"
    policy_trace: QueryPolicyTrace = field(default_factory=QueryPolicyTrace)

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
    retrieval_trace: QueryRetrievalExecutionTrace | None = None


@dataclass(frozen=True, slots=True)
class QueryRetrievalExecutionTrace:
    planned_queries: tuple[str, ...] = ()
    executed_queries: tuple[str, ...] = ()
    merged_raw_hit_count: int = 0
    merged_result_count: int = 0
    stop_reason: str | None = None


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
