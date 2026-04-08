# ruff: noqa: RUF001

from __future__ import annotations

import re

from app.services.knowledge_base.query.classifier import classify_query_intent
from app.services.knowledge_base.query.rule_matcher import match_rule_evidence
from app.services.knowledge_base.query.scope import detect_query_scope


def test_match_rule_evidence_requires_contains_all_fragments() -> None:
    evidence = match_rule_evidence(
        "що є в парку",
        contains_any=(),
        contains_all=("програм",),
        regex_patterns=(),
    )
    assert evidence == []


def test_match_rule_evidence_requires_contains_any_when_declared() -> None:
    evidence = match_rule_evidence(
        "розкажи про трансфер",
        contains_any=("розваги", "програми"),
        contains_all=(),
        regex_patterns=(),
    )
    assert evidence == []


def test_match_rule_evidence_allows_contains_fragments_without_regex_match() -> None:
    evidence = match_rule_evidence(
        "що можна в парку",
        contains_any=("що можна",),
        contains_all=(),
        regex_patterns=(re.compile(r"«[^»]+»"),),
    )
    assert evidence == ["що можна"]


def test_match_rule_evidence_returns_regex_evidence_when_regex_matches() -> None:
    evidence = match_rule_evidence(
        'порівняй "Програма А" або "Програма Б"',
        contains_any=(),
        contains_all=(),
        regex_patterns=(re.compile(r'"[^"]+".*\bабо\b.*"[^"]+"', flags=re.UNICODE),),
    )
    assert evidence


def test_classifier_regression_still_detects_enumeration_intent() -> None:
    classification = classify_query_intent("Які є види організованих програм?")
    assert classification.intent == "enumeration"
    assert classification.matched_rules


def test_scope_regression_still_detects_transfer_scope() -> None:
    scope = detect_query_scope("Чи є у вас трансфер до парку?")
    assert "transfer" in scope.scopes
    assert scope.matched_rules
