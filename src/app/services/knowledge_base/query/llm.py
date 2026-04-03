from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.knowledge_base.normalizer import normalize_cell_text
from app.services.knowledge_base.query.retrieval_planner import (
    MAX_RETRIEVAL_ALTERNATE_QUERIES,
    MAX_RETRIEVAL_KEYWORDS,
    MAX_RETRIEVAL_QUERY_LENGTH,
)
from app.services.knowledge_base.query.types import (
    QueryClassification,
    QueryIntent,
    QueryInterpretationStage,
    QueryRetrievalHints,
    QueryRetrievalPlan,
    QueryScopeDetection,
    QueryScopeName,
    QueryStrategy,
)

MAX_DEBUG_NOTE_LENGTH = 160
MAX_LLM_COMPLETION_TOKENS = 220
PROMPT_GUIDE_PATH = Path(__file__).with_name("llm_prompt_guide.md")


@dataclass(frozen=True, slots=True)
class QueryInterpretationRequest:
    query: str
    normalized_query: str
    requested_stages: tuple[QueryInterpretationStage, ...]
    deterministic_classification: QueryClassification
    deterministic_scope_detection: QueryScopeDetection
    deterministic_strategy: QueryStrategy
    deterministic_retrieval_plan: QueryRetrievalPlan


@dataclass(frozen=True, slots=True)
class QueryInterpretationResult:
    intent: QueryIntent
    scope: QueryScopeName
    strategy: QueryStrategy
    confidence: float
    debug_note: str | None = None
    retrieval_hints: QueryRetrievalHints | None = None


class QueryInterpreter(Protocol):
    def interpret(self, request: QueryInterpretationRequest) -> QueryInterpretationResult:
        """Return structured query interpretation without free-form answer text."""


class _OpenAIRetrievalHintsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_query: str = Field(min_length=1, max_length=MAX_RETRIEVAL_QUERY_LENGTH)
    alternate_queries: list[str] = Field(
        default_factory=list,
        max_length=MAX_RETRIEVAL_ALTERNATE_QUERIES,
    )
    keywords: list[str] = Field(default_factory=list, max_length=MAX_RETRIEVAL_KEYWORDS)
    confidence: float = Field(ge=0.0, le=1.0)
    debug_note: str | None = Field(default=None, max_length=MAX_DEBUG_NOTE_LENGTH)

    @field_validator("primary_query")
    @classmethod
    def normalize_primary_query(cls, value: str) -> str:
        normalized = normalize_cell_text(value).strip()
        if not normalized:
            msg = "retrieval.primary_query must not be empty."
            raise ValueError(msg)
        return normalized[:MAX_RETRIEVAL_QUERY_LENGTH]

    @field_validator("alternate_queries", mode="after")
    @classmethod
    def normalize_alternate_queries(cls, values: list[str]) -> list[str]:
        normalized = _normalize_list(values, item_limit=MAX_RETRIEVAL_QUERY_LENGTH)
        return normalized[:MAX_RETRIEVAL_ALTERNATE_QUERIES]

    @field_validator("keywords", mode="after")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        normalized = _normalize_list(values, item_limit=32)
        return normalized[:MAX_RETRIEVAL_KEYWORDS]


class _OpenAIInterpretationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: QueryIntent
    scope: QueryScopeName
    strategy: QueryStrategy
    confidence: float = Field(ge=0.0, le=1.0)
    debug_note: str | None = Field(default=None, max_length=MAX_DEBUG_NOTE_LENGTH)
    retrieval: _OpenAIRetrievalHintsPayload | None = None


class OpenAIQueryInterpreter:
    """OpenAI-backed structured query interpretation adapter."""

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

    def interpret(self, request: QueryInterpretationRequest) -> QueryInterpretationResult:
        response = self._client.responses.parse(
            model=self._model,
            instructions=(
                "Return only the structured route and retrieval hints for this Berry Land "
                "knowledge-base query. Use only schema-supported enum values and short "
                "KB-native phrases."
            ),
            input=_build_prompt(request),
            text_format=_OpenAIInterpretationPayload,
            temperature=0,
            max_output_tokens=MAX_LLM_COMPLETION_TOKENS,
            reasoning={"effort": "none"},
            store=False,
            timeout=self._timeout_seconds,
        )
        parsed = response.output_parsed
        if parsed is None:
            msg = "OpenAI returned no parsed query interpretation."
            raise ValueError(msg)

        retrieval_hints = None
        if parsed.retrieval is not None:
            retrieval_hints = QueryRetrievalHints(
                primary_query=parsed.retrieval.primary_query,
                alternate_queries=tuple(parsed.retrieval.alternate_queries),
                keywords=tuple(parsed.retrieval.keywords),
                confidence=round(parsed.retrieval.confidence, 2),
                debug_note=parsed.retrieval.debug_note,
            )

        return QueryInterpretationResult(
            intent=parsed.intent,
            scope=parsed.scope,
            strategy=parsed.strategy,
            confidence=round(parsed.confidence, 2),
            debug_note=parsed.debug_note,
            retrieval_hints=retrieval_hints,
        )


def _build_prompt(request: QueryInterpretationRequest) -> str:
    requested = ", ".join(request.requested_stages)
    retrieval_keywords = ", ".join(request.deterministic_retrieval_plan.keywords) or "(none)"
    retrieval_alternates = (
        " | ".join(request.deterministic_retrieval_plan.alternate_queries) or "(none)"
    )
    return "\n\n".join(
        (
            _load_prompt_guide(),
            "\n".join(
                (
                    "[Request]",
                    f"query={request.query}",
                    f"normalized_query={request.normalized_query}",
                    f"requested_stages={requested}",
                    (
                        "deterministic_intent="
                        f"{request.deterministic_classification.intent}"
                        f" confidence={request.deterministic_classification.confidence}"
                    ),
                    (
                        "deterministic_scope="
                        f"{request.deterministic_scope_detection.primary_scope}"
                        f" confidence={request.deterministic_scope_detection.confidence}"
                    ),
                    f"deterministic_strategy={request.deterministic_strategy}",
                    (
                        "deterministic_retrieval_primary="
                        f"{request.deterministic_retrieval_plan.primary_query}"
                    ),
                    f"deterministic_retrieval_alternates={retrieval_alternates}",
                    f"deterministic_retrieval_keywords={retrieval_keywords}",
                    (
                        "For stages not requested, keep the deterministic/default value. "
                        "If retrieval is requested, prefer short Berry Land phrases "
                        "that match the guide."
                    ),
                )
            ),
        )
    )


@lru_cache(maxsize=1)
def _load_prompt_guide() -> str:
    return PROMPT_GUIDE_PATH.read_text(encoding="utf-8").strip()


def _normalize_list(values: list[str], *, item_limit: int) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_cell_text(value).strip()
        if not normalized:
            continue
        normalized = normalized[:item_limit]
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped
