from __future__ import annotations

import logging
from collections import defaultdict

from app.services.knowledge_base.query.rule_matcher import match_rule_evidence
from app.services.knowledge_base.query.rules import INTENT_RULES, INTENT_TIE_BREAK_ORDER
from app.services.knowledge_base.query.text import normalize_query_text
from app.services.knowledge_base.query.types import QueryClassification, QueryIntent, RuleMatch

logger = logging.getLogger(__name__)

LOG_EVENT_QUERY_CLASSIFIED = "kb_query_classified"


def classify_query_intent(query: str) -> QueryClassification:
    normalized_query = normalize_query_text(query)
    matched_rules = tuple(_match_intent_rules(normalized_query))
    if not matched_rules:
        classification = QueryClassification(
            intent="unknown",
            confidence=0.0,
            matched_rules=(),
            rationale=("No intent rules matched.",),
        )
        logger.info("%s intent=%s confidence=%s", LOG_EVENT_QUERY_CLASSIFIED, "unknown", 0.0)
        return classification

    grouped: dict[QueryIntent, list[RuleMatch]] = defaultdict(list)
    for rule in matched_rules:
        grouped[_intent_for_rule(rule.rule_id)].append(rule)

    intent = _choose_intent(grouped)
    chosen_rules = tuple(sorted(grouped[intent], key=lambda item: (-item.priority, item.rule_id)))
    confidence = min(
        1.0,
        max(0.0, _confidence_for_rule(intent, chosen_rules[0].rule_id))
        + max(0, len(chosen_rules) - 1) * 0.03,
    )
    classification = QueryClassification(
        intent=intent,
        confidence=round(confidence, 2),
        matched_rules=chosen_rules,
        rationale=tuple(rule.description for rule in chosen_rules),
    )
    logger.info(
        "%s intent=%s confidence=%s rule_count=%s",
        LOG_EVENT_QUERY_CLASSIFIED,
        classification.intent,
        classification.confidence,
        len(classification.matched_rules),
    )
    return classification


def _match_intent_rules(query: str) -> list[RuleMatch]:
    matches: list[RuleMatch] = []
    for rule in INTENT_RULES:
        evidence = match_rule_evidence(
            query,
            rule.contains_any,
            rule.contains_all,
            rule.regex_patterns,
        )
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


def _choose_intent(grouped: dict[QueryIntent, list[RuleMatch]]) -> QueryIntent:
    tie_break_index = {intent: index for index, intent in enumerate(INTENT_TIE_BREAK_ORDER)}
    ranked = sorted(
        grouped.items(),
        key=lambda item: (
            -max(rule.priority for rule in item[1]),
            -sum(rule.priority for rule in item[1]),
            -len(item[1]),
            tie_break_index[item[0]],
        ),
    )
    return ranked[0][0]


def _intent_for_rule(rule_id: str) -> QueryIntent:
    for rule in INTENT_RULES:
        if rule.rule_id == rule_id:
            return rule.intent
    return "unknown"


def _confidence_for_rule(intent: QueryIntent, rule_id: str) -> float:
    for rule in INTENT_RULES:
        if rule.rule_id == rule_id and rule.intent == intent:
            return rule.confidence
    return 0.0

