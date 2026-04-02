# ruff: noqa: RUF001

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.knowledge_base.query_types import QueryIntent, QueryScopeName

INTENT_TIE_BREAK_ORDER: tuple[QueryIntent, ...] = (
    "comparison",
    "enumeration",
    "overview",
    "detail",
    "unknown",
)
SCOPE_TIE_BREAK_ORDER: tuple[QueryScopeName, ...] = (
    "programs",
    "services",
    "park_activities",
    "food",
    "zones",
    "pricing",
    "transfer",
    "general",
)


@dataclass(frozen=True, slots=True)
class IntentRuleDefinition:
    rule_id: str
    intent: QueryIntent
    priority: int
    confidence: float
    description: str
    contains_any: tuple[str, ...] = ()
    contains_all: tuple[str, ...] = ()
    regex_patterns: tuple[re.Pattern[str], ...] = ()


@dataclass(frozen=True, slots=True)
class ScopeRuleDefinition:
    rule_id: str
    scope: QueryScopeName
    priority: int
    confidence: float
    description: str
    contains_any: tuple[str, ...] = ()
    contains_all: tuple[str, ...] = ()
    regex_patterns: tuple[re.Pattern[str], ...] = ()


INTENT_RULES: tuple[IntentRuleDefinition, ...] = (
    IntentRuleDefinition(
        rule_id="comparison_explicit_compare",
        intent="comparison",
        priority=100,
        confidence=0.99,
        description="Explicit compare/difference wording",
        contains_any=(
            "порівняй",
            "порівняйте",
            "яка різниця",
            "чим відрізняється",
            "чим різниться",
            "відмінність між",
        ),
    ),
    IntentRuleDefinition(
        rule_id="comparison_two_named_options",
        intent="comparison",
        priority=95,
        confidence=0.95,
        description="Two named options joined by 'або'",
        regex_patterns=(
            re.compile(r"«[^»]+».*\bабо\b.*«[^»]+»", flags=re.IGNORECASE | re.UNICODE),
            re.compile(r'"[^"]+".*\bабо\b.*"[^"]+"', flags=re.IGNORECASE | re.UNICODE),
        ),
    ),
    IntentRuleDefinition(
        rule_id="enumeration_program_types",
        intent="enumeration",
        priority=95,
        confidence=0.99,
        description="Explicit request for program list/types",
        contains_any=("види програм", "перелік програм", "список програм", "назви програм", "види"),
        contains_all=("програм",),
    ),
    IntentRuleDefinition(
        rule_id="enumeration_which_programs",
        intent="enumeration",
        priority=90,
        confidence=0.93,
        description="Broad question asking which programs exist",
        contains_any=("які є", "які у вас", "які саме"),
        contains_all=("програм",),
    ),
    IntentRuleDefinition(
        rule_id="overview_offer_request",
        intent="overview",
        priority=95,
        confidence=0.99,
        description="Direct request for general offer overview",
        contains_any=(
            "що ви можете мені запропонувати",
            "що ви можете запропонувати",
            "що можете мені запропонувати",
            "що можете запропонувати",
        ),
    ),
    IntentRuleDefinition(
        rule_id="overview_general_options",
        intent="overview",
        priority=90,
        confidence=0.92,
        description="Broad question about available activities/services",
        contains_any=(
            "що у вас є",
            "що можна у вас",
            "що можна в парку",
            "що є в парку",
            "які у вас розваги",
            "як провести час",
            "як можна відпочити",
        ),
    ),
    IntentRuleDefinition(
        rule_id="detail_specific_request",
        intent="detail",
        priority=80,
        confidence=0.85,
        description="Specific factual/detail wording",
        contains_any=(
            "що входить",
            "скільки коштує",
            "яка вартість",
            "ціна",
            "вартість",
            "коли",
            "де",
            "чи є",
            "розклад",
            "тривалість",
            "умови",
            "знижки",
        ),
    ),
)

SCOPE_RULES: tuple[ScopeRuleDefinition, ...] = (
    ScopeRuleDefinition(
        rule_id="scope_programs",
        scope="programs",
        priority=100,
        confidence=0.95,
        description="Program catalog or organized program terms",
        contains_any=(
            "організован",
            "програм",
            "випускн",
            "тімбілд",
            "експедиці",
            "berry bubble",
            "back to school",
            "місія",
        ),
    ),
    ScopeRuleDefinition(
        rule_id="scope_services",
        scope="services",
        priority=95,
        confidence=0.92,
        description="Extra services and operational services",
        contains_any=(
            "послуг",
            "сервіс",
            "альтан",
            "кафе",
            "бар",
            "магазин",
            "бронюван",
            "трансфер",
        ),
    ),
    ScopeRuleDefinition(
        rule_id="scope_park_activities",
        scope="park_activities",
        priority=92,
        confidence=0.92,
        description="General park activities and ways to spend time",
        contains_any=(
            "розваг",
            "відпоч",
            "актив",
            "що можна",
            "ігров",
            "поні",
            "басейн",
            "екскурс",
            "майданчик",
            "водні",
        ),
    ),
    ScopeRuleDefinition(
        rule_id="scope_food",
        scope="food",
        priority=88,
        confidence=0.9,
        description="Food, meals, cafe, tasting",
        contains_any=("харч", "їжа", "обід", "кафе", "частуван", "поїсти", "бар"),
    ),
    ScopeRuleDefinition(
        rule_id="scope_zones",
        scope="zones",
        priority=88,
        confidence=0.88,
        description="Zones and areas of the park",
        contains_any=("зона", "територ", "майданчик", "ранчо", "ферма", "теплиц", "кемпінг"),
    ),
    ScopeRuleDefinition(
        rule_id="scope_pricing",
        scope="pricing",
        priority=90,
        confidence=0.93,
        description="Pricing, tickets, discounts",
        contains_any=("вартіст", "ціна", "квит", "знижк"),
    ),
    ScopeRuleDefinition(
        rule_id="scope_transfer",
        scope="transfer",
        priority=90,
        confidence=0.92,
        description="Transfer and transport wording",
        contains_any=("трансфер", "автобус", "доїхати"),
    ),
)
