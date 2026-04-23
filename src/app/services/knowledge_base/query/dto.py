from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, TypedDict

AttributeScalar = str | int | float | bool
VectorAttributes = dict[str, AttributeScalar]
EvidenceSourceType = Literal["vector", "lexical"]
AnswerState = Literal["answered", "clarification", "fallback"]


class RoutingFlags(TypedDict):
    scope: str
    scopes: tuple[str, ...]
    strategy: str
    needs_retrieval: bool
    needs_structure: bool
    policy_mode: str
    intent_source: str
    scope_source: str
    strategy_source: str
    retrieval_source: str


class RewriteLexicalPayload(TypedDict):
    keywords: tuple[str, ...]
    synonyms: tuple[str, ...]
    phrases: tuple[str, ...]


class RewriteFiltersPayload(TypedDict):
    category: str | None
    logical_id: str | None
    language: str
    attribute_filters: VectorAttributes


def _tuple_of_str(values: object) -> tuple[str, ...]:
    if isinstance(values, tuple):
        return tuple(str(value) for value in values)
    if isinstance(values, list):
        return tuple(str(value) for value in values)
    return ()


def _tuple_to_list(values: tuple[str, ...]) -> list[str]:
    return [str(value) for value in values]


def _attributes_from_mapping(value: object) -> VectorAttributes:
    if not isinstance(value, dict):
        return {}
    attributes: VectorAttributes = {}
    for key, raw in value.items():
        if isinstance(raw, bool | int | float | str):
            attributes[str(key)] = raw
    return attributes


def _routing_flags_from_dict(value: object) -> RoutingFlags:
    payload = value if isinstance(value, dict) else {}
    return {
        "scope": str(payload.get("scope", "")),
        "scopes": _tuple_of_str(payload.get("scopes")),
        "strategy": str(payload.get("strategy", "")),
        "needs_retrieval": bool(payload.get("needs_retrieval", False)),
        "needs_structure": bool(payload.get("needs_structure", False)),
        "policy_mode": str(payload.get("policy_mode", "")),
        "intent_source": str(payload.get("intent_source", "")),
        "scope_source": str(payload.get("scope_source", "")),
        "strategy_source": str(payload.get("strategy_source", "")),
        "retrieval_source": str(payload.get("retrieval_source", "")),
    }


def _routing_flags_to_dict(flags: RoutingFlags) -> dict[str, object]:
    return {
        "scope": flags["scope"],
        "scopes": _tuple_to_list(flags["scopes"]),
        "strategy": flags["strategy"],
        "needs_retrieval": flags["needs_retrieval"],
        "needs_structure": flags["needs_structure"],
        "policy_mode": flags["policy_mode"],
        "intent_source": flags["intent_source"],
        "scope_source": flags["scope_source"],
        "strategy_source": flags["strategy_source"],
        "retrieval_source": flags["retrieval_source"],
    }


def _rewrite_lexical_from_dict(value: object) -> RewriteLexicalPayload:
    payload = value if isinstance(value, dict) else {}
    return {
        "keywords": _tuple_of_str(payload.get("keywords")),
        "synonyms": _tuple_of_str(payload.get("synonyms")),
        "phrases": _tuple_of_str(payload.get("phrases")),
    }


def _rewrite_lexical_to_dict(payload: RewriteLexicalPayload) -> dict[str, object]:
    return {
        "keywords": _tuple_to_list(payload["keywords"]),
        "synonyms": _tuple_to_list(payload["synonyms"]),
        "phrases": _tuple_to_list(payload["phrases"]),
    }


def _rewrite_filters_from_dict(value: object) -> RewriteFiltersPayload:
    payload = value if isinstance(value, dict) else {}
    return {
        "category": (
            str(payload["category"])
            if payload.get("category") is not None
            else None
        ),
        "logical_id": (
            str(payload["logical_id"])
            if payload.get("logical_id") is not None
            else None
        ),
        "language": str(payload.get("language", "uk")),
        "attribute_filters": _attributes_from_mapping(payload.get("attribute_filters")),
    }


def _rewrite_filters_to_dict(payload: RewriteFiltersPayload) -> dict[str, object]:
    return {
        "category": payload["category"],
        "logical_id": payload["logical_id"],
        "language": payload["language"],
        "attribute_filters": dict(payload["attribute_filters"]),
    }


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class NormalizedQuery:
    raw_text: str
    user_locale: str
    detected_language: str
    canonical_uk: str
    created_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "raw_text": self.raw_text,
            "user_locale": self.user_locale,
            "detected_language": self.detected_language,
            "canonical_uk": self.canonical_uk,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> NormalizedQuery:
        return cls(
            raw_text=str(payload["raw_text"]),
            user_locale=str(payload["user_locale"]),
            detected_language=str(payload["detected_language"]),
            canonical_uk=str(payload["canonical_uk"]),
            created_at=_parse_datetime(payload["created_at"]),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> NormalizedQuery:
        return cls.from_dict(json.loads(payload))


@dataclass(frozen=True, slots=True)
class RouterDecision:
    intent: str
    needs_clarification: bool
    clarification_question: str | None
    missing_slots: tuple[str, ...] = ()
    routing_flags: RoutingFlags = field(
        default_factory=lambda: {
            "scope": "",
            "scopes": (),
            "strategy": "",
            "needs_retrieval": False,
            "needs_structure": False,
            "policy_mode": "",
            "intent_source": "",
            "scope_source": "",
            "strategy_source": "",
            "retrieval_source": "",
        }
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "needs_clarification": self.needs_clarification,
            "clarification_question": self.clarification_question,
            "missing_slots": _tuple_to_list(self.missing_slots),
            "routing_flags": _routing_flags_to_dict(self.routing_flags),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RouterDecision:
        return cls(
            intent=str(payload["intent"]),
            needs_clarification=bool(payload["needs_clarification"]),
            clarification_question=(
                str(payload["clarification_question"])
                if payload.get("clarification_question") is not None
                else None
            ),
            missing_slots=_tuple_of_str(payload.get("missing_slots")),
            routing_flags=_routing_flags_from_dict(payload.get("routing_flags")),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> RouterDecision:
        return cls.from_dict(json.loads(payload))


@dataclass(frozen=True, slots=True)
class RewriteResult:
    canonical_uk: str
    vector_query_uk: str
    lexical: RewriteLexicalPayload
    filters: RewriteFiltersPayload

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_uk": self.canonical_uk,
            "vector_query_uk": self.vector_query_uk,
            "lexical": _rewrite_lexical_to_dict(self.lexical),
            "filters": _rewrite_filters_to_dict(self.filters),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RewriteResult:
        return cls(
            canonical_uk=str(payload["canonical_uk"]),
            vector_query_uk=str(payload["vector_query_uk"]),
            lexical=_rewrite_lexical_from_dict(payload.get("lexical")),
            filters=_rewrite_filters_from_dict(payload.get("filters")),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> RewriteResult:
        return cls.from_dict(json.loads(payload))


@dataclass(frozen=True, slots=True)
class VectorHit:
    section_id: str
    file_id: str
    score: float
    text: str
    attributes: VectorAttributes = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "file_id": self.file_id,
            "score": self.score,
            "text": self.text,
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> VectorHit:
        return cls(
            section_id=str(payload["section_id"]),
            file_id=str(payload["file_id"]),
            score=float(payload["score"]),
            text=str(payload["text"]),
            attributes=_attributes_from_mapping(payload.get("attributes")),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> VectorHit:
        return cls.from_dict(json.loads(payload))


@dataclass(frozen=True, slots=True)
class LexicalHit:
    section_id: str
    bm25: float
    heading_path: tuple[str, ...]
    content: str

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "bm25": self.bm25,
            "heading_path": _tuple_to_list(self.heading_path),
            "content": self.content,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> LexicalHit:
        return cls(
            section_id=str(payload["section_id"]),
            bm25=float(payload["bm25"]),
            heading_path=_tuple_of_str(payload.get("heading_path")),
            content=str(payload["content"]),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> LexicalHit:
        return cls.from_dict(json.loads(payload))


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    section_id: str
    source_type: EvidenceSourceType
    title: str
    content: str
    score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "source_type": self.source_type,
            "title": self.title,
            "content": self.content,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> EvidenceItem:
        return cls(
            section_id=str(payload["section_id"]),
            source_type=str(payload["source_type"]),
            title=str(payload["title"]),
            content=str(payload["content"]),
            score=float(payload["score"]),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> EvidenceItem:
        return cls.from_dict(json.loads(payload))


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    items: tuple[EvidenceItem, ...]
    token_budget_used: int
    truncation_applied: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "items": [item.to_dict() for item in self.items],
            "token_budget_used": self.token_budget_used,
            "truncation_applied": self.truncation_applied,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> EvidencePacket:
        raw_items = payload.get("items", [])
        items = tuple(
            EvidenceItem.from_dict(item)
            for item in raw_items
            if isinstance(item, dict)
        )
        return cls(
            items=items,
            token_budget_used=int(payload["token_budget_used"]),
            truncation_applied=bool(payload["truncation_applied"]),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> EvidencePacket:
        return cls.from_dict(json.loads(payload))


@dataclass(frozen=True, slots=True)
class AnswerResult:
    state: AnswerState
    answer_text: str
    clarification_question: str | None
    source_section_ids: tuple[str, ...] = ()
    debug_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "answer_text": self.answer_text,
            "clarification_question": self.clarification_question,
            "source_section_ids": _tuple_to_list(self.source_section_ids),
            "debug_reason": self.debug_reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> AnswerResult:
        return cls(
            state=str(payload["state"]),
            answer_text=str(payload["answer_text"]),
            clarification_question=(
                str(payload["clarification_question"])
                if payload.get("clarification_question") is not None
                else None
            ),
            source_section_ids=_tuple_of_str(payload.get("source_section_ids")),
            debug_reason=(
                str(payload["debug_reason"])
                if payload.get("debug_reason") is not None
                else None
            ),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> AnswerResult:
        return cls.from_dict(json.loads(payload))
