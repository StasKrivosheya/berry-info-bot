from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Literal, Protocol

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import OpenAIReasoningEffort
from app.services.knowledge_base.taxonomy import GENERAL_TOPIC_ID, get_default_taxonomy

# ruff: noqa: RUF001

QueryRouteName = Literal[
    "greeting",
    "smalltalk",
    "menu_help",
    "follow_up",
    "kb_query",
    "unsupported",
]
ClarificationKind = Literal["topic", "direction"]
QuerySpecificity = Literal["vague", "concrete"]
QuestionScope = Literal["unknown", "broad", "direction_specific"]
ResponseKind = Literal["service", "menu", "clarification", "search", "fallback"]

MAX_MESSAGE_LENGTH = 1000
MAX_QUERY_LENGTH = 500
MAX_LIST_ITEM_LENGTH = 80
MAX_LIST_ITEMS = 8
MAX_OUTPUT_TOKENS = 500
DEFAULT_CONTEXT_TTL_SECONDS = 15 * 60
MAX_CONTEXT_TURNS = 4
MAX_DETERMINISTIC_FOLLOW_UP_WORDS = 7
MAX_CLARIFICATION_REPLY_WORDS = 5

TOKEN_RE = re.compile(r"[\w'’]+", re.UNICODE)

logger = logging.getLogger(__name__)

SERVICE_FALLBACK_TEXT = (
    "Я віртуальний менеджер Berry Land. Скористайтеся кнопками меню або напишіть "
    "запитання про парк."
)
FOLLOW_UP_CLARIFICATION_TEXT = "Уточніть, будь ласка, про який напрям ви питаєте?"

QUERY_ROUTER_BASE_PROMPT = """
You route Berry Land Telegram messages. Return only the QueryRoute schema.

Routes:
- greeting: hello/hi without a concrete task.
- smalltalk: casual chat not about Berry Land services.
- menu_help: asks to show menu, buttons, contacts navigation, or available sections.
- kb_query: asks about Berry Land facts, prices, schedule, programs, services, transfer,
  food, zones.
- follow_up: short continuation that depends on previous context.
- unsupported: unrelated, unsafe, or impossible for the Berry Land KB.

Rules:
- reply_language must be "uk".
- For kb_query and resolvable follow_up, fill canonical_question_uk, vector_query_uk,
  lexical_keywords, lexical_phrases, and confidence.
- For kb_query and resolvable follow_up, set topic_hint and direction_hints only from
  the controlled vocabulary below. Use [] when unsure.
- direction_hints is the business direction list: OP/SV/camping/birthdays/school
  excursions. Use one item for one direction and multiple items only when the user
  explicitly asks about multiple directions.
- topic_hint is the question topic: tickets/schedule/programs/transfer/food/etc.
- target_date is a concise date/month/season from the user message when present.
- query_specificity is "concrete" for a specific fact, object, amenity, rule, service,
  availability, schedule, or price question; use "vague" only for generic requests like
  "tell me more" or "I want information".
- question_scope is "direction_specific" when the user names OP/SV/etc.; "broad" when
  they ask about the park overall or all directions; otherwise "unknown".
- If a concrete KB question has no controlled topic, keep topic_hint null and search
  broadly. Do not ask topic clarification for concrete entity/amenity questions.
- Direction clarification is deterministic and configured per topic. When no direction is
  mentioned, leave direction_hints empty; the app decides whether clarification is needed.
- Never invent category names.
- Translate Russian/English user questions into concise Ukrainian canonical/vector queries
  and Ukrainian lexical terms. Keep the original user wording only as supporting search text.
- Use previous context only for a short follow_up; set use_context=true when used.
- If follow_up has no useful context, leave query fields empty and ask for clarification later.
- Do not answer the user and do not reveal reasoning.
""".strip()
QUERY_ROUTER_PROMPT = "\n\n".join(
    (
        QUERY_ROUTER_BASE_PROMPT,
        get_default_taxonomy().build_router_prompt_section(),
    )
)


class QueryRoute(BaseModel):
    """Single production contract for free-text routing and KB canonicalization."""

    model_config = ConfigDict(extra="forbid")

    route: QueryRouteName
    original_message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    reply_language: Literal["uk"] = "uk"
    canonical_question_uk: str | None = Field(default=None, max_length=MAX_QUERY_LENGTH)
    vector_query_uk: str | None = Field(default=None, max_length=MAX_QUERY_LENGTH)
    lexical_keywords: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    lexical_phrases: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    use_context: bool = False
    topic_hint: str | None = Field(default=None, max_length=80)
    direction_hints: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    target_date: str | None = Field(default=None, max_length=80)
    category_hint: str | None = Field(default=None, max_length=80)
    logical_id_hint: str | None = Field(default=None, max_length=120)
    query_specificity: QuerySpecificity = "concrete"
    question_scope: QuestionScope = "unknown"
    clarification_reason: str | None = Field(default=None, max_length=160)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator(
        "original_message",
        "canonical_question_uk",
        "vector_query_uk",
        "topic_hint",
        "target_date",
        "category_hint",
        "logical_id_hint",
        "clarification_reason",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        normalized = " ".join(str(value).strip().split())
        return normalized or None

    @field_validator("lexical_keywords", "lexical_phrases", "direction_hints", mode="after")
    @classmethod
    def normalize_text_list(cls, values: list[str]) -> list[str]:
        return list(normalize_unique_texts(tuple(values)))

    @model_validator(mode="after")
    def validate_searchable_routes(self) -> QueryRoute:
        if self.route == "kb_query" or (self.route == "follow_up" and self.use_context):
            if (
                not self.canonical_question_uk
                or not self.vector_query_uk
                or not self.lexical_keywords
                or not self.lexical_phrases
            ):
                msg = (
                    "Searchable routes require canonical_question_uk, vector_query_uk, "
                    "lexical_keywords, and lexical_phrases."
                )
                raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class QueryContextKey:
    chat_id: int
    user_id: int


@dataclass(frozen=True, slots=True)
class QueryTurn:
    user_message: str
    route_name: QueryRouteName | None
    query_specificity: QuerySpecificity | None
    question_scope: QuestionScope | None
    topic_hint: str | None
    direction_hints: tuple[str, ...]
    response_kind: ResponseKind
    clarification_kind: ClarificationKind | None = None
    answer_state: str | None = None
    accepted_candidate_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QueryContext:
    original_message: str
    canonical_question_uk: str
    vector_query_uk: str
    lexical_keywords: tuple[str, ...]
    lexical_phrases: tuple[str, ...]
    topic_hint: str | None
    direction_hints: tuple[str, ...]
    target_date: str | None
    category_hint: str | None
    logical_id_hint: str | None
    query_specificity: QuerySpecificity
    question_scope: QuestionScope
    clarification_reason: str | None = None
    pending_clarification: ClarificationKind | None = None
    history: tuple[QueryTurn, ...] = ()


@dataclass(frozen=True, slots=True)
class QueryRoutingResult:
    route: QueryRoute | None
    response_text: str
    should_search: bool
    used_context: bool = False
    clarification_kind: ClarificationKind | None = None


class QueryRouter(Protocol):
    def route(self, message: str, *, context: QueryContext | None = None) -> QueryRoute:
        """Return a structured free-text route without answering the user."""


class QueryContextStore:
    """Tiny in-memory TTL context store for resolving short follow-up messages."""

    def __init__(
        self,
        *,
        ttl_seconds: int = DEFAULT_CONTEXT_TTL_SECONDS,
        monotonic=time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._monotonic = monotonic
        self._items: dict[QueryContextKey, tuple[float, QueryContext]] = {}

    def get(self, key: QueryContextKey) -> QueryContext | None:
        item = self._items.get(key)
        if item is None:
            return None

        created_at, context = item
        if self._monotonic() - created_at > self._ttl_seconds:
            self._items.pop(key, None)
            return None
        return context

    def save(
        self,
        key: QueryContextKey,
        route: QueryRoute,
        *,
        pending_clarification: ClarificationKind | None = None,
    ) -> None:
        self.save_turn(
            key,
            route=route,
            message=route.original_message,
            response_kind="clarification" if pending_clarification else "search",
            pending_clarification=pending_clarification,
            clarification_kind=pending_clarification,
        )

    def save_turn(
        self,
        key: QueryContextKey,
        *,
        route: QueryRoute | None,
        message: str,
        response_kind: ResponseKind,
        pending_clarification: ClarificationKind | None = None,
        clarification_kind: ClarificationKind | None = None,
        answer_state: str | None = None,
        accepted_candidate_ids: tuple[str, ...] = (),
    ) -> None:
        previous = self.get(key)
        context_values = _context_values_from_route(route)
        if context_values is None and previous is not None:
            context_values = _context_values_from_context(previous)
        if context_values is None:
            context_values = {
                "original_message": message.strip(),
                "canonical_question_uk": "",
                "vector_query_uk": "",
                "lexical_keywords": (),
                "lexical_phrases": (),
                "topic_hint": None,
                "direction_hints": (),
                "target_date": None,
                "category_hint": None,
                "logical_id_hint": None,
                "query_specificity": "vague",
                "question_scope": "unknown",
                "clarification_reason": None,
            }

        history = _append_context_turn(
            previous.history if previous is not None else (),
            QueryTurn(
                user_message=message.strip(),
                route_name=route.route if route is not None else None,
                query_specificity=route.query_specificity if route is not None else None,
                question_scope=route.question_scope if route is not None else None,
                topic_hint=route.topic_hint if route is not None else None,
                direction_hints=tuple(route.direction_hints) if route is not None else (),
                response_kind=response_kind,
                clarification_kind=clarification_kind,
                answer_state=answer_state,
                accepted_candidate_ids=accepted_candidate_ids,
            ),
        )

        self._items[key] = (
            self._monotonic(),
            QueryContext(
                **context_values,
                pending_clarification=pending_clarification,
                history=history,
            ),
        )

    def update_last_answer(
        self,
        key: QueryContextKey,
        *,
        answer_state: str,
        accepted_candidate_ids: tuple[str, ...],
    ) -> None:
        context = self.get(key)
        if context is None or not context.history:
            return
        last_turn = context.history[-1]
        updated_turn = QueryTurn(
            user_message=last_turn.user_message,
            route_name=last_turn.route_name,
            query_specificity=last_turn.query_specificity,
            question_scope=last_turn.question_scope,
            topic_hint=last_turn.topic_hint,
            direction_hints=last_turn.direction_hints,
            response_kind=last_turn.response_kind,
            clarification_kind=last_turn.clarification_kind,
            answer_state=answer_state,
            accepted_candidate_ids=accepted_candidate_ids,
        )
        self._items[key] = (
            self._monotonic(),
            QueryContext(
                original_message=context.original_message,
                canonical_question_uk=context.canonical_question_uk,
                vector_query_uk=context.vector_query_uk,
                lexical_keywords=context.lexical_keywords,
                lexical_phrases=context.lexical_phrases,
                topic_hint=context.topic_hint,
                direction_hints=context.direction_hints,
                target_date=context.target_date,
                category_hint=context.category_hint,
                logical_id_hint=context.logical_id_hint,
                query_specificity=context.query_specificity,
                question_scope=context.question_scope,
                clarification_reason=context.clarification_reason,
                pending_clarification=context.pending_clarification,
                history=(*context.history[:-1], updated_turn),
            ),
        )


class OpenAIQueryRouter:
    """OpenAI-backed structured router for normal free-text Telegram messages."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: int,
        reasoning_effort: OpenAIReasoningEffort | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._reasoning_effort = reasoning_effort
        self._client = client or OpenAI(api_key=api_key, timeout=timeout_seconds)

    def route(self, message: str, *, context: QueryContext | None = None) -> QueryRoute:
        payload = {
            "model": self._model,
            "instructions": QUERY_ROUTER_PROMPT,
            "input": build_query_router_input(message, context=context),
            "text_format": QueryRoute,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "store": False,
            "timeout": self._timeout_seconds,
        }
        if self._reasoning_effort is not None:
            payload["reasoning"] = {"effort": self._reasoning_effort}
        response = self._client.responses.parse(**payload)
        parsed = response.output_parsed
        if parsed is None:
            msg = "OpenAI returned no parsed query route."
            raise ValueError(msg)
        return parsed


def build_query_router_input(message: str, *, context: QueryContext | None) -> str:
    context_lines = ["Previous context: none"]
    if context is not None:
        turn_lines = ["- none"]
        if context.history:
            turn_lines = [
                (
                    f"- user_message={turn.user_message}; route={turn.route_name or '(none)'}; "
                    f"response_kind={turn.response_kind}; "
                    f"topic_hint={turn.topic_hint or '(none)'}; "
                    f"direction_hints={', '.join(turn.direction_hints) or '(none)'}; "
                    f"clarification_kind={turn.clarification_kind or '(none)'}; "
                    f"answer_state={turn.answer_state or '(none)'}; "
                    f"accepted_candidate_ids={', '.join(turn.accepted_candidate_ids) or '(none)'}"
                )
                for turn in context.history
            ]
        context_lines = [
            "Previous context:",
            f"- original_message: {context.original_message}",
            f"- canonical_question_uk: {context.canonical_question_uk or '(none)'}",
            f"- vector_query_uk: {context.vector_query_uk or '(none)'}",
            f"- lexical_keywords: {', '.join(context.lexical_keywords) or '(none)'}",
            f"- lexical_phrases: {', '.join(context.lexical_phrases) or '(none)'}",
            f"- topic_hint: {context.topic_hint or '(none)'}",
            f"- direction_hints: {', '.join(context.direction_hints) or '(none)'}",
            f"- target_date: {context.target_date or '(none)'}",
            f"- category_hint: {context.category_hint or '(none)'}",
            f"- logical_id_hint: {context.logical_id_hint or '(none)'}",
            f"- query_specificity: {context.query_specificity}",
            f"- question_scope: {context.question_scope}",
            f"- clarification_reason: {context.clarification_reason or '(none)'}",
            f"- pending_clarification: {context.pending_clarification or '(none)'}",
            "Recent turns:",
            *turn_lines,
        ]
    return "\n".join(
        (
            f"User message: {message.strip()}",
            "",
            *context_lines,
        )
    )


def route_free_text_message(
    *,
    router: QueryRouter,
    context_store: QueryContextStore,
    context_key: QueryContextKey,
    message: str,
) -> QueryRoutingResult:
    context = context_store.get(context_key)
    route = resolve_pending_clarification_message(message=message, context=context)
    if route is not None:
        return build_routing_result(
            route=route,
            context_store=context_store,
            context_key=context_key,
            used_context=True,
            message=message,
        )

    try:
        route = router.route(message, context=context)
    except Exception:
        route = resolve_contextual_short_follow_up(message=message, context=context)
        if route is not None:
            return build_routing_result(
                route=route,
                context_store=context_store,
                context_key=context_key,
                used_context=True,
                message=message,
            )
        context_store.save_turn(
            context_key,
            route=None,
            message=message,
            response_kind="fallback",
        )
        return QueryRoutingResult(
            route=None,
            response_text=SERVICE_FALLBACK_TEXT,
            should_search=False,
        )
    route = normalize_route_taxonomy(route, context=context)
    route = promote_contextual_short_follow_up(route, message=message, context=context)
    route = rescue_likely_kb_query(route, message=message)

    return build_routing_result(
        route=route,
        context_store=context_store,
        context_key=context_key,
        used_context=route.use_context,
        message=message,
    )


def build_routing_result(
    *,
    route: QueryRoute,
    context_store: QueryContextStore,
    context_key: QueryContextKey,
    used_context: bool,
    message: str,
) -> QueryRoutingResult:
    if route.route == "menu_help":
        context_store.save_turn(
            context_key,
            route=route,
            message=message,
            response_kind="menu",
        )
        return QueryRoutingResult(
            route=route,
            response_text="",
            should_search=False,
            used_context=used_context,
        )

    if route.route == "follow_up" and not route.use_context:
        context_store.save_turn(
            context_key,
            route=route,
            message=message,
            response_kind="clarification",
            clarification_kind="direction",
        )
        return QueryRoutingResult(
            route=route,
            response_text=FOLLOW_UP_CLARIFICATION_TEXT,
            should_search=False,
            used_context=False,
        )

    if route.route in {"kb_query", "follow_up"}:
        taxonomy = get_default_taxonomy()
        if taxonomy.should_clarify_topic(
            topic_id=route.topic_hint,
            query_specificity=route.query_specificity,
        ):
            route = route.model_copy(
                update={
                    "clarification_reason": route.clarification_reason
                    or "topic_unclear_for_vague_query",
                },
            )
            context_store.save_turn(
                context_key,
                route=route,
                message=message,
                response_kind="clarification",
                pending_clarification="topic",
                clarification_kind="topic",
            )
            return QueryRoutingResult(
                route=route,
                response_text=taxonomy.build_topic_clarification_text(),
                should_search=False,
                used_context=used_context,
                clarification_kind="topic",
            )
        if taxonomy.should_clarify_direction(
            topic_id=route.topic_hint,
            direction_ids=tuple(route.direction_hints),
        ):
            route = route.model_copy(
                update={
                    "clarification_reason": route.clarification_reason
                    or "direction_required_for_topic",
                },
            )
            context_store.save_turn(
                context_key,
                route=route,
                message=message,
                response_kind="clarification",
                pending_clarification="direction",
                clarification_kind="direction",
            )
            return QueryRoutingResult(
                route=route,
                response_text=taxonomy.build_direction_clarification_text(route.topic_hint),
                should_search=False,
                used_context=used_context,
                clarification_kind="direction",
            )
        context_store.save_turn(
            context_key,
            route=route,
            message=message,
            response_kind="search",
        )
        return QueryRoutingResult(
            route=route,
            response_text=SERVICE_FALLBACK_TEXT,
            should_search=True,
            used_context=used_context,
        )

    context_store.save_turn(
        context_key,
        route=route,
        message=message,
        response_kind="service",
    )
    return QueryRoutingResult(
        route=route,
        response_text=SERVICE_FALLBACK_TEXT,
        should_search=False,
        used_context=used_context,
    )


def resolve_pending_clarification_message(
    *,
    message: str,
    context: QueryContext | None,
) -> QueryRoute | None:
    if context is None or context.pending_clarification is None:
        return None
    if not _is_option_like_clarification_reply(message):
        return None

    taxonomy = get_default_taxonomy()
    direction_ids = taxonomy.infer_direction_ids_from_text(message)
    topic_ids = taxonomy.infer_topic_ids_from_text(message)

    if context.pending_clarification == "direction" and direction_ids:
        return build_contextual_route(
            message=message,
            context=context,
            topic_hint=context.topic_hint,
            direction_hints=direction_ids,
        )

    if context.pending_clarification == "topic" and topic_ids:
        return build_contextual_route(
            message=message,
            context=context,
            topic_hint=topic_ids[0],
            direction_hints=direction_ids,
        )

    return None


def resolve_contextual_short_follow_up(
    *,
    message: str,
    context: QueryContext | None,
) -> QueryRoute | None:
    if context is None or context.pending_clarification is not None:
        return None
    if len(message.strip().split()) > MAX_DETERMINISTIC_FOLLOW_UP_WORDS:
        return None
    if not context.vector_query_uk or not _looks_like_short_follow_up(message):
        return None

    taxonomy = get_default_taxonomy()
    topic_ids = taxonomy.infer_topic_ids_from_text(message)
    direction_ids = taxonomy.infer_direction_ids_from_text(message)
    if not topic_ids and not direction_ids:
        return None

    return build_contextual_route(
        message=message,
        context=context,
        topic_hint=topic_ids[0] if topic_ids else context.topic_hint,
        direction_hints=direction_ids or context.direction_hints,
    )


def promote_contextual_short_follow_up(
    route: QueryRoute,
    *,
    message: str,
    context: QueryContext | None,
) -> QueryRoute:
    if context is None or context.pending_clarification is not None:
        return route
    if route.use_context or len(message.strip().split()) > MAX_DETERMINISTIC_FOLLOW_UP_WORDS:
        return route
    if not _looks_like_short_follow_up(message):
        return route
    if route.route not in {"greeting", "smalltalk", "unsupported", "follow_up"}:
        return route

    contextual_route = resolve_contextual_short_follow_up(message=message, context=context)
    return contextual_route or route


def build_contextual_route(
    *,
    message: str,
    context: QueryContext,
    topic_hint: str | None,
    direction_hints: tuple[str, ...],
) -> QueryRoute:
    taxonomy = get_default_taxonomy()
    normalized_direction_ids = taxonomy.normalize_direction_ids(direction_hints)
    if not normalized_direction_ids and context.direction_hints:
        normalized_direction_ids = context.direction_hints

    topic_label = taxonomy.topics.get(topic_hint or "")
    direction_text = _direction_text(normalized_direction_ids)
    topic_text = topic_label.label_uk if topic_label is not None else ""

    canonical_question = _join_non_empty(
        context.canonical_question_uk,
        f"Уточнення користувача: {message.strip()}.",
        f"Тема: {topic_text}." if topic_text else "",
        f"Напрямок: {direction_text}." if direction_text else "",
    )
    vector_query = _join_non_empty(
        context.vector_query_uk,
        message.strip(),
        topic_text,
        direction_text,
    )
    lexical_keywords = _extend_unique(
        (
            *context.lexical_keywords,
            message.strip(),
            topic_text,
            *_direction_keywords(normalized_direction_ids),
        ),
    )
    lexical_phrases = _extend_unique(
        (*context.lexical_phrases, message.strip(), topic_text, direction_text),
    )

    return QueryRoute(
        route="follow_up",
        original_message=message.strip() or context.original_message,
        canonical_question_uk=canonical_question,
        vector_query_uk=vector_query,
        lexical_keywords=list(lexical_keywords),
        lexical_phrases=list(lexical_phrases),
        use_context=True,
        topic_hint=topic_hint,
        direction_hints=list(normalized_direction_ids),
        target_date=context.target_date,
        category_hint=context.category_hint,
        logical_id_hint=context.logical_id_hint,
        query_specificity="concrete",
        question_scope="direction_specific" if normalized_direction_ids else "broad",
        clarification_reason="contextual_short_follow_up",
        confidence=0.85,
    )


def normalize_route_taxonomy(
    route: QueryRoute,
    *,
    context: QueryContext | None,
) -> QueryRoute:
    taxonomy = get_default_taxonomy()
    route_text = "\n".join(
        part
        for part in (
            route.original_message,
            route.canonical_question_uk or "",
            route.vector_query_uk or "",
            " ".join(route.lexical_keywords),
            " ".join(route.lexical_phrases),
        )
        if part
    )
    direction_text = route.original_message
    topic_hint = taxonomy.normalize_topic_id(route.topic_hint)
    if topic_hint is None:
        topic_hint = taxonomy.normalize_topic_id(route.category_hint)
    if topic_hint is None:
        inferred_topics = taxonomy.infer_topic_ids_from_text(route_text)
        topic_hint = inferred_topics[0] if inferred_topics else None
    if topic_hint == GENERAL_TOPIC_ID and route.query_specificity == "concrete":
        topic_hint = None
    if topic_hint is None and route.use_context and context is not None:
        topic_hint = context.topic_hint

    direction_ids = taxonomy.normalize_direction_ids(tuple(route.direction_hints))
    category_direction = taxonomy.normalize_direction_id(route.category_hint)
    if category_direction is not None and category_direction not in direction_ids:
        direction_ids = (*direction_ids, category_direction)
    for direction_id in taxonomy.infer_direction_ids_from_text(direction_text):
        if direction_id not in direction_ids:
            direction_ids = (*direction_ids, direction_id)
    if not direction_ids and route.use_context and context is not None:
        if context.direction_hints:
            direction_ids = context.direction_hints

    question_scope = route.question_scope
    if direction_ids:
        question_scope = "direction_specific"
    elif route.route in {"kb_query", "follow_up"} and question_scope == "unknown":
        question_scope = "broad"

    target_date = route.target_date
    if target_date is None and route.use_context and context is not None:
        target_date = context.target_date

    return route.model_copy(
        update={
            "topic_hint": topic_hint,
            "direction_hints": list(direction_ids),
            "question_scope": question_scope,
            "target_date": target_date,
        }
    )


def rescue_likely_kb_query(route: QueryRoute, *, message: str) -> QueryRoute:
    if route.route not in {"smalltalk", "unsupported"}:
        return route
    if not _looks_like_kb_query(message):
        return route

    original_message = message.strip() or route.original_message
    lexical_keywords = _extract_lexical_terms(original_message)
    vector_query = _join_non_empty(route.vector_query_uk or original_message, "Berry Land")
    logger.info(
        "kb_query_route_rescued original_route=%s message=%r",
        route.route,
        original_message,
    )
    return QueryRoute(
        route="kb_query",
        original_message=original_message,
        canonical_question_uk=route.canonical_question_uk or original_message,
        vector_query_uk=vector_query,
        lexical_keywords=list(lexical_keywords or ("Berry Land",)),
        lexical_phrases=list(
            normalize_unique_texts((original_message, route.canonical_question_uk or vector_query)),
        ),
        topic_hint=route.topic_hint,
        direction_hints=route.direction_hints,
        target_date=route.target_date,
        category_hint=route.category_hint,
        logical_id_hint=route.logical_id_hint,
        query_specificity="concrete",
        question_scope="direction_specific" if route.direction_hints else "broad",
        clarification_reason="deterministic_kb_rescue",
        confidence=min(route.confidence, 0.55),
    )


def _context_values_from_route(route: QueryRoute | None) -> dict[str, object] | None:
    if route is None or route.route not in {"kb_query", "follow_up"}:
        return None
    if not route.canonical_question_uk or not route.vector_query_uk:
        return None
    return {
        "original_message": route.original_message,
        "canonical_question_uk": route.canonical_question_uk,
        "vector_query_uk": route.vector_query_uk,
        "lexical_keywords": tuple(route.lexical_keywords),
        "lexical_phrases": tuple(route.lexical_phrases),
        "topic_hint": route.topic_hint,
        "direction_hints": tuple(route.direction_hints),
        "target_date": route.target_date,
        "category_hint": route.category_hint,
        "logical_id_hint": route.logical_id_hint,
        "query_specificity": route.query_specificity,
        "question_scope": route.question_scope,
        "clarification_reason": route.clarification_reason,
    }


def _context_values_from_context(context: QueryContext) -> dict[str, object]:
    return {
        "original_message": context.original_message,
        "canonical_question_uk": context.canonical_question_uk,
        "vector_query_uk": context.vector_query_uk,
        "lexical_keywords": context.lexical_keywords,
        "lexical_phrases": context.lexical_phrases,
        "topic_hint": context.topic_hint,
        "direction_hints": context.direction_hints,
        "target_date": context.target_date,
        "category_hint": context.category_hint,
        "logical_id_hint": context.logical_id_hint,
        "query_specificity": context.query_specificity,
        "question_scope": context.question_scope,
        "clarification_reason": context.clarification_reason,
    }


def _append_context_turn(
    history: tuple[QueryTurn, ...],
    turn: QueryTurn,
) -> tuple[QueryTurn, ...]:
    return (*history, turn)[-MAX_CONTEXT_TURNS:]


def _is_option_like_clarification_reply(message: str) -> bool:
    stripped = message.strip()
    if not stripped or "\n" in stripped:
        return False
    word_count = len(stripped.split())
    if word_count > MAX_CLARIFICATION_REPLY_WORDS:
        return False
    if "?" in stripped and word_count > 2:
        return False
    return True


def _looks_like_short_follow_up(message: str) -> bool:
    stripped = message.strip()
    if not stripped:
        return False
    taxonomy = get_default_taxonomy()
    if taxonomy.infer_direction_ids_from_text(stripped):
        return True
    normalized = stripped.casefold()
    return (
        "?" in stripped
        or normalized.startswith(("а ", "і ", "и ", "а?", "і?", "и?"))
        or normalized in {"а", "і", "и"}
    )


def _looks_like_kb_query(message: str) -> bool:
    normalized = message.strip().casefold()
    if not normalized:
        return False
    domain_terms = (
        "berry",
        "land",
        "парк",
        "парку",
        "парке",
        "парка",
        "квит",
        "білет",
        "билет",
        "ціна",
        "цена",
        "граф",
        "розклад",
        "распис",
        "трансфер",
        "послуг",
        "услуг",
        "програм",
        "харч",
        "еда",
        "їжа",
        "локац",
        "адрес",
        "можна",
        "можно",
        "ticket",
        "price",
        "schedule",
        "transfer",
        "service",
        "program",
        "food",
        "where",
        "what",
        "available",
    )
    if any(term in normalized for term in domain_terms):
        return True
    return "?" in normalized and not _looks_like_social_message(normalized)


def _looks_like_social_message(normalized: str) -> bool:
    social_terms = (
        "привіт",
        "вітаю",
        "здравствуйте",
        "добрый день",
        "дякую",
        "спасибо",
        "как дела",
        "як справи",
        "hello",
        "hi",
        "thanks",
    )
    return any(term in normalized for term in social_terms)


def _extract_lexical_terms(message: str) -> tuple[str, ...]:
    stopwords = {
        "the",
        "and",
        "what",
        "where",
        "how",
        "berry",
        "land",
        "парк",
        "парку",
        "парке",
        "парка",
        "are",
        "есть",
        "какие",
        "какой",
        "які",
        "який",
        "що",
        "что",
        "для",
        "про",
        "мене",
        "вас",
    }
    values: list[str] = []
    for match in TOKEN_RE.finditer(message):
        token = match.group(0).strip("'’").casefold()
        if len(token) < 3 or token in stopwords:
            continue
        if token not in values:
            values.append(token)
        if len(values) >= MAX_LIST_ITEMS:
            break
    return tuple(values)


def _direction_text(direction_ids: tuple[str, ...]) -> str:
    taxonomy = get_default_taxonomy()
    labels: list[str] = []
    for direction_id in direction_ids:
        direction = taxonomy.directions.get(direction_id)
        if direction is None:
            labels.append(direction_id)
            continue
        labels.append(f"{direction.short_label} {direction.label_uk}")
    return ", ".join(labels)


def _direction_keywords(direction_ids: tuple[str, ...]) -> tuple[str, ...]:
    taxonomy = get_default_taxonomy()
    values: list[str] = []
    for direction_id in direction_ids:
        direction = taxonomy.directions.get(direction_id)
        if direction is None:
            values.append(direction_id)
            continue
        values.extend((direction.short_label, direction.label_uk))
    return tuple(values)


def _join_non_empty(*parts: str) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def _extend_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return normalize_unique_texts(values)


def normalize_unique_texts(values: tuple[str, ...]) -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(str(value).strip().split())[:MAX_LIST_ITEM_LENGTH]
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return tuple(output[:MAX_LIST_ITEMS])
