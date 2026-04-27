from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal, Protocol

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ruff: noqa: RUF001

QueryRouteName = Literal[
    "greeting",
    "smalltalk",
    "menu_help",
    "follow_up",
    "kb_query",
    "unsupported",
]

MAX_MESSAGE_LENGTH = 1000
MAX_QUERY_LENGTH = 500
MAX_LIST_ITEM_LENGTH = 80
MAX_LIST_ITEMS = 8
MAX_OUTPUT_TOKENS = 500
DEFAULT_CONTEXT_TTL_SECONDS = 15 * 60

SERVICE_FALLBACK_TEXT = (
    "Я віртуальний менеджер Berry Land. Скористайтеся кнопками меню або напишіть "
    "запитання про парк."
)
FOLLOW_UP_CLARIFICATION_TEXT = "Уточніть, будь ласка, про що саме ви питаєте."

QUERY_ROUTER_PROMPT = """
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
- Translate Russian/English user questions into concise Ukrainian canonical/vector queries.
- Use previous context only for a short follow_up; set use_context=true when used.
- If follow_up has no useful context, leave query fields empty and ask for clarification later.
- Do not answer the user and do not reveal reasoning.
""".strip()


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
    category_hint: str | None = Field(default=None, max_length=80)
    logical_id_hint: str | None = Field(default=None, max_length=120)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator(
        "original_message",
        "canonical_question_uk",
        "vector_query_uk",
        "category_hint",
        "logical_id_hint",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        normalized = " ".join(str(value).strip().split())
        return normalized or None

    @field_validator("lexical_keywords", "lexical_phrases", mode="after")
    @classmethod
    def normalize_list(cls, values: list[str]) -> list[str]:
        normalized_values: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = " ".join(str(value).strip().split())[:MAX_LIST_ITEM_LENGTH]
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized_values.append(normalized)
        return normalized_values[:MAX_LIST_ITEMS]

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
class QueryContext:
    original_message: str
    canonical_question_uk: str
    vector_query_uk: str
    lexical_keywords: tuple[str, ...]
    lexical_phrases: tuple[str, ...]
    category_hint: str | None
    logical_id_hint: str | None


@dataclass(frozen=True, slots=True)
class QueryRoutingResult:
    route: QueryRoute | None
    response_text: str
    should_search: bool
    used_context: bool = False


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

    def save(self, key: QueryContextKey, route: QueryRoute) -> None:
        if route.route not in {"kb_query", "follow_up"}:
            return
        if not route.canonical_question_uk or not route.vector_query_uk:
            return

        self._items[key] = (
            self._monotonic(),
            QueryContext(
                original_message=route.original_message,
                canonical_question_uk=route.canonical_question_uk,
                vector_query_uk=route.vector_query_uk,
                lexical_keywords=tuple(route.lexical_keywords),
                lexical_phrases=tuple(route.lexical_phrases),
                category_hint=route.category_hint,
                logical_id_hint=route.logical_id_hint,
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
        client: OpenAI | None = None,
    ) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = client or OpenAI(api_key=api_key, timeout=timeout_seconds)

    def route(self, message: str, *, context: QueryContext | None = None) -> QueryRoute:
        response = self._client.responses.parse(
            model=self._model,
            instructions=QUERY_ROUTER_PROMPT,
            input=build_query_router_input(message, context=context),
            text_format=QueryRoute,
            temperature=0,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            reasoning={"effort": "none"},
            store=False,
            timeout=self._timeout_seconds,
        )
        parsed = response.output_parsed
        if parsed is None:
            msg = "OpenAI returned no parsed query route."
            raise ValueError(msg)
        return parsed


def build_query_router_input(message: str, *, context: QueryContext | None) -> str:
    context_lines = ["Previous context: none"]
    if context is not None:
        context_lines = [
            "Previous context:",
            f"- original_message: {context.original_message}",
            f"- canonical_question_uk: {context.canonical_question_uk}",
            f"- vector_query_uk: {context.vector_query_uk}",
            f"- lexical_keywords: {', '.join(context.lexical_keywords) or '(none)'}",
            f"- lexical_phrases: {', '.join(context.lexical_phrases) or '(none)'}",
            f"- category_hint: {context.category_hint or '(none)'}",
            f"- logical_id_hint: {context.logical_id_hint or '(none)'}",
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
    try:
        route = router.route(message, context=context)
    except Exception:
        return QueryRoutingResult(
            route=None,
            response_text=SERVICE_FALLBACK_TEXT,
            should_search=False,
        )

    if route.route == "menu_help":
        return QueryRoutingResult(
            route=route,
            response_text="",
            should_search=False,
            used_context=route.use_context,
        )

    if route.route == "follow_up" and not route.use_context:
        return QueryRoutingResult(
            route=route,
            response_text=FOLLOW_UP_CLARIFICATION_TEXT,
            should_search=False,
            used_context=False,
        )

    if route.route in {"kb_query", "follow_up"}:
        context_store.save(context_key, route)
        return QueryRoutingResult(
            route=route,
            response_text=SERVICE_FALLBACK_TEXT,
            should_search=True,
            used_context=route.use_context,
        )

    return QueryRoutingResult(
        route=route,
        response_text=SERVICE_FALLBACK_TEXT,
        should_search=False,
        used_context=route.use_context,
    )
