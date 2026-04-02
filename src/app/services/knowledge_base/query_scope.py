from __future__ import annotations

import logging
from collections import defaultdict

from app.services.knowledge_base.query_rules import SCOPE_RULES, SCOPE_TIE_BREAK_ORDER
from app.services.knowledge_base.query_text import normalize_query_text
from app.services.knowledge_base.query_types import QueryScopeDetection, QueryScopeName, RuleMatch

logger = logging.getLogger(__name__)

LOG_EVENT_SCOPE_DETECTED = "kb_query_scope_detected"


def detect_query_scope(query: str) -> QueryScopeDetection:
    normalized_query = normalize_query_text(query)
    matched_rules = tuple(_match_scope_rules(normalized_query))
    if not matched_rules:
        detection = QueryScopeDetection(
            primary_scope="general",
            scopes=("general",),
            confidence=0.0,
            matched_rules=(),
            rationale=("No scope rules matched.",),
        )
        logger.info("%s scope=%s confidence=%s", LOG_EVENT_SCOPE_DETECTED, "general", 0.0)
        return detection

    grouped: dict[QueryScopeName, list[RuleMatch]] = defaultdict(list)
    for rule in matched_rules:
        grouped[_scope_for_rule(rule.rule_id)].append(rule)

    scope_scores = sorted(
        grouped.items(),
        key=lambda item: (
            -max(rule.priority for rule in item[1]),
            -sum(rule.priority for rule in item[1]),
            -len(item[1]),
            {scope: index for index, scope in enumerate(SCOPE_TIE_BREAK_ORDER)}[item[0]],
        ),
    )
    ordered_scopes = tuple(scope for scope, _ in scope_scores)
    primary_scope = ordered_scopes[0]
    chosen_rules = tuple(
        sorted(
            [rule for scope in ordered_scopes for rule in grouped[scope]],
            key=lambda item: (-item.priority, item.rule_id),
        )
    )
    confidence = min(
        1.0,
        max(0.0, _confidence_for_rule(primary_scope, chosen_rules[0].rule_id))
        + max(0, len(grouped[primary_scope]) - 1) * 0.03,
    )
    detection = QueryScopeDetection(
        primary_scope=primary_scope,
        scopes=ordered_scopes,
        confidence=round(confidence, 2),
        matched_rules=chosen_rules,
        rationale=tuple(rule.description for rule in chosen_rules),
    )
    logger.info(
        "%s scope=%s confidence=%s scope_count=%s",
        LOG_EVENT_SCOPE_DETECTED,
        detection.primary_scope,
        detection.confidence,
        len(detection.scopes),
    )
    return detection


def _match_scope_rules(query: str) -> list[RuleMatch]:
    matches: list[RuleMatch] = []
    for rule in SCOPE_RULES:
        evidence = _match_rule(query, rule.contains_any, rule.contains_all, rule.regex_patterns)
        if not evidence:
            continue
        matches.append(
            RuleMatch(
                rule_id=rule.rule_id,
                priority=rule.priority,
                description=rule.description,
                evidence=tuple(evidence),
            )
        )
    return matches


def _match_rule(
    query: str,
    contains_any: tuple[str, ...],
    contains_all: tuple[str, ...],
    regex_patterns,
) -> list[str]:
    evidence: list[str] = []

    if contains_all:
        missing = [fragment for fragment in contains_all if fragment not in query]
        if missing:
            return []
        evidence.extend(contains_all)

    if contains_any:
        matched_any = [fragment for fragment in contains_any if fragment in query]
        if not matched_any:
            return []
        evidence.extend(matched_any)

    regex_evidence = [pattern.pattern for pattern in regex_patterns if pattern.search(query)]
    if regex_patterns and not regex_evidence and not evidence:
        return []
    evidence.extend(regex_evidence)

    return evidence


def _scope_for_rule(rule_id: str) -> QueryScopeName:
    for rule in SCOPE_RULES:
        if rule.rule_id == rule_id:
            return rule.scope
    return "general"


def _confidence_for_rule(scope: QueryScopeName, rule_id: str) -> float:
    for rule in SCOPE_RULES:
        if rule.rule_id == rule_id and rule.scope == scope:
            return rule.confidence
    return 0.0
