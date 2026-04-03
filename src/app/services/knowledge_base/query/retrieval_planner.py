from __future__ import annotations

from dataclasses import dataclass

from app.services.knowledge_base.normalizer import normalize_cell_text
from app.services.knowledge_base.query.text import normalize_query_text
from app.services.knowledge_base.query.types import (
    QueryClassification,
    QueryDecisionSource,
    QueryRetrievalHints,
    QueryRetrievalPlan,
    QueryScopeDetection,
    QueryStrategy,
)

MAX_RETRIEVAL_QUERY_LENGTH = 120
MAX_RETRIEVAL_ALTERNATE_QUERIES = 3
MAX_RETRIEVAL_KEYWORDS = 6


@dataclass(frozen=True, slots=True)
class RetrievalAliasRule:
    rule_id: str
    description: str
    confidence: float
    contains_any: tuple[str, ...]
    primary_query: str
    alternate_queries: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


RETRIEVAL_ALIAS_RULES: tuple[RetrievalAliasRule, ...] = (
    RetrievalAliasRule(
        rule_id="animals_zoo_to_pony_farm",
        description="Expanded zoo and animal wording to canonical Berry Land farm terms.",
        confidence=0.92,
        contains_any=(
            "зоопарк",
            "зоопарку",
            "тварини",
            "тварин",
            "тваринок",
            "альпака",
            "альпаки",
            "козлик",
            "козлики",
        ),
        primary_query="екскурсія на поні-ферму тварини ранчо",
        alternate_queries=(
            "ферма до тваринок Berry Land",
            "поні-ферма тварини ранчо",
        ),
        keywords=("поні-ферма", "тварини", "ранчо", "ферма"),
    ),
)


def build_deterministic_retrieval_plan(
    query: str,
    classification: QueryClassification,
    scope_detection: QueryScopeDetection,
    strategy: QueryStrategy,
) -> QueryRetrievalPlan:
    normalized_query = normalize_query_text(query)
    matched_rule = next(
        (
            rule
            for rule in RETRIEVAL_ALIAS_RULES
            if any(fragment in normalized_query for fragment in rule.contains_any)
        ),
        None,
    )
    if matched_rule is not None:
        return build_retrieval_plan(
            default_query=query,
            primary_query=matched_rule.primary_query,
            alternate_queries=matched_rule.alternate_queries,
            keywords=matched_rule.keywords,
            confidence=matched_rule.confidence,
            source="rules",
            rationale=(
                matched_rule.description,
                f"Alias rule matched: {matched_rule.rule_id}.",
            ),
            debug_note=(
                "Expanded the retrieval query to Berry Land farm terms such as "
                "поні-ферма, ранчо, and тварини."
            ),
        )

    return build_retrieval_plan(
        default_query=query,
        primary_query=query,
        alternate_queries=(),
        keywords=_default_keywords(
            query=query,
            classification=classification,
            scope_detection=scope_detection,
            strategy=strategy,
        ),
        confidence=0.0,
        source="rules",
        rationale=("Using the raw query as the deterministic retrieval baseline.",),
    )


def build_retrieval_plan(
    *,
    default_query: str,
    primary_query: str,
    alternate_queries: tuple[str, ...] | list[str] = (),
    keywords: tuple[str, ...] | list[str] = (),
    confidence: float,
    source: QueryDecisionSource,
    rationale: tuple[str, ...] = (),
    debug_note: str | None = None,
) -> QueryRetrievalPlan:
    normalized_primary = _normalize_query(primary_query) or _normalize_query(default_query)
    normalized_default = _normalize_query(default_query)
    normalized_alternates = tuple(
        _dedupe(
            query
            for query in (
                _normalize_query(value)
                for value in alternate_queries[:MAX_RETRIEVAL_ALTERNATE_QUERIES]
            )
            if query and query not in {normalized_primary, normalized_default}
        )
    )
    normalized_keywords = tuple(
        _dedupe(
            keyword
            for keyword in (
                _normalize_keyword(value) for value in keywords[:MAX_RETRIEVAL_KEYWORDS]
            )
            if keyword
        )
    )
    return QueryRetrievalPlan(
        primary_query=normalized_primary,
        alternate_queries=normalized_alternates,
        keywords=normalized_keywords,
        confidence=round(max(0.0, min(1.0, confidence)), 2),
        source=source,
        rationale=rationale,
        debug_note=debug_note,
    )


def build_retrieval_plan_from_hints(
    *,
    default_query: str,
    hints: QueryRetrievalHints,
    source: QueryDecisionSource,
    rationale: tuple[str, ...] = (),
) -> QueryRetrievalPlan:
    return build_retrieval_plan(
        default_query=default_query,
        primary_query=hints.primary_query,
        alternate_queries=hints.alternate_queries,
        keywords=hints.keywords,
        confidence=hints.confidence,
        source=source,
        rationale=rationale,
        debug_note=hints.debug_note,
    )


def _default_keywords(
    *,
    query: str,
    classification: QueryClassification,
    scope_detection: QueryScopeDetection,
    strategy: QueryStrategy,
) -> tuple[str, ...]:
    normalized_query = normalize_query_text(query)
    keywords: list[str] = []
    if "поні-ферма" in normalized_query or "поні ферма" in normalized_query:
        keywords.extend(("поні-ферма", "поні", "ферма"))
    elif scope_detection.primary_scope in {"park_activities", "zones"} and strategy in {
        "detail_retrieval",
        "safe_fallback",
    }:
        if classification.intent in {"detail", "unknown"}:
            keywords.extend(("активності", scope_detection.primary_scope.replace("_", " ")))
    return tuple(_dedupe(keywords))


def _normalize_query(value: str | None) -> str:
    if value is None:
        return ""
    normalized = normalize_cell_text(value).strip()
    if not normalized:
        return ""
    return normalized[:MAX_RETRIEVAL_QUERY_LENGTH]


def _normalize_keyword(value: str | None) -> str:
    if value is None:
        return ""
    normalized = normalize_cell_text(value).strip()
    if not normalized:
        return ""
    return normalized[:32]


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped
