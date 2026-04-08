# ruff: noqa: RUF001

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.knowledge_base.query.llm import (
    MAX_LLM_COMPLETION_TOKENS,
    OpenAIQueryInterpreter,
    QueryInterpretationRequest,
    _OpenAIRetrievalHintsPayload,
)
from app.services.knowledge_base.query.retrieval_planner import build_retrieval_plan
from app.services.knowledge_base.query.types import QueryClassification, QueryScopeDetection


class FakeResponsesAPI:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        output_parsed = SimpleNamespace(
            intent="detail",
            scope="park_activities",
            strategy="detail_retrieval",
            confidence=0.91,
            debug_note="Animal query routed to park activities.",
            retrieval=SimpleNamespace(
                primary_query="екскурсія на поні-ферму тварини ранчо",
                alternate_queries=["ферма до тваринок Berry Land"],
                keywords=["поні-ферма", "тварини", "ранчо"],
                confidence=0.94,
                debug_note="Mapped zoo wording to pony-farm terms.",
            ),
        )
        return SimpleNamespace(output_parsed=output_parsed)


class FakeOpenAIClient:
    def __init__(self, parse_api: FakeResponsesAPI) -> None:
        self.responses = parse_api


def test_openai_query_interpreter_uses_responses_parse_with_reasoning_none() -> None:
    parse_api = FakeResponsesAPI()
    interpreter = OpenAIQueryInterpreter(
        api_key="test-key",
        model="gpt-5.4-nano",
        timeout_seconds=10,
        client=FakeOpenAIClient(parse_api),  # type: ignore[arg-type]
    )
    request = QueryInterpretationRequest(
        query="хто у вас є в зоопарку?",
        normalized_query="хто у вас є в зоопарку?",
        requested_stages=("classifier", "scope", "planner", "retrieval"),
        deterministic_classification=QueryClassification(intent="unknown", confidence=0.0),
        deterministic_scope_detection=QueryScopeDetection(
            primary_scope="general",
            scopes=("general",),
            confidence=0.0,
        ),
        deterministic_strategy="safe_fallback",
        deterministic_retrieval_plan=build_retrieval_plan(
            default_query="хто у вас є в зоопарку?",
            primary_query="екскурсія на поні-ферму тварини ранчо",
            alternate_queries=("ферма до тваринок Berry Land",),
            keywords=("поні-ферма", "тварини"),
            confidence=0.92,
            source="rules",
        ),
    )

    result = interpreter.interpret(request)

    assert result.intent == "detail"
    assert result.retrieval_hints is not None
    assert result.retrieval_hints.primary_query == "екскурсія на поні-ферму тварини ранчо"
    assert parse_api.kwargs is not None
    assert parse_api.kwargs["model"] == "gpt-5.4-nano"
    assert parse_api.kwargs["temperature"] == 0
    assert parse_api.kwargs["max_output_tokens"] == MAX_LLM_COMPLETION_TOKENS
    assert parse_api.kwargs["store"] is False
    assert parse_api.kwargs["timeout"] == 10
    assert parse_api.kwargs["reasoning"] == {"effort": "none"}
    assert parse_api.kwargs["instructions"]
    assert parse_api.kwargs["input"]
    assert "Berry Land Query Routing Guide" in str(parse_api.kwargs["input"])
    assert parse_api.kwargs["text_format"]


def test_retrieval_payload_normalizes_and_dedupes_lists() -> None:
    payload = _OpenAIRetrievalHintsPayload(
        primary_query="  екскурсія на поні-ферму  ",
        alternate_queries=[
            " ферма до тваринок Berry Land ",
            "ферма до тваринок Berry Land",
            "",
        ],
        keywords=[" поні-ферма ", "тварини", "поні-ферма"],
        confidence=0.9,
        debug_note="note",
    )

    assert payload.primary_query == "екскурсія на поні-ферму"
    assert payload.alternate_queries == ["ферма до тваринок Berry Land"]
    assert payload.keywords == ["поні-ферма", "тварини"]


def test_retrieval_payload_rejects_empty_primary_query() -> None:
    with pytest.raises(ValueError, match="primary_query"):
        _OpenAIRetrievalHintsPayload(
            primary_query="   ",
            alternate_queries=[],
            keywords=[],
            confidence=0.4,
        )
