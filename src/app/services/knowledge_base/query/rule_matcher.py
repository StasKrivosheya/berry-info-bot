from __future__ import annotations

import re

RegexPatterns = tuple[re.Pattern[str], ...]


def match_rule_evidence(
    query: str,
    contains_any: tuple[str, ...],
    contains_all: tuple[str, ...],
    regex_patterns: RegexPatterns,
) -> list[str]:
    """Return deterministic evidence fragments when a rule matches query text."""

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
