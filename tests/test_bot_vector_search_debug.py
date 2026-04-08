# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram.filters import CommandObject

from app.bot.handlers.debug import query_debug
from app.bot.handlers.debug.vector_search_debug import (
    VS_USAGE_TEXT,
    extract_query_text,
    format_search_messages,
    split_for_telegram,
)
from app.services.knowledge_base.query.types import (
    AnswerBlock,
    QueryAnswerResult,
    QueryClassification,
    QueryPlan,
    QueryPolicyTrace,
    QueryRetrievalExecutionTrace,
    QueryRetrievalPlan,
    QueryScopeDetection,
    QueryStageToggles,
    SearchHitDebugContext,
)
from app.services.knowledge_base.types_openai import SearchHit, SearchResponse


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
    ) -> SimpleNamespace:
        self.calls.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
        )
        return SimpleNamespace(message_id=len(self.calls))


class FakeMessage:
    def __init__(self, bot: FakeBot, *, user_id: int = 1001) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(id=2002)
        self.bot = bot


class SuccessfulRetrievalService:
    def __init__(self, response: SearchResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> SearchResponse:
        self.calls.append(kwargs)
        return self.response


class FailingRetrievalService:
    def search(self, **kwargs: object) -> SearchResponse:
        raise RuntimeError("search backend unavailable")


class FakeStructureReader:
    def resolve_hit_context(self, hit: SearchHit) -> SearchHitDebugContext:
        return SearchHitDebugContext(
            logical_id=str(hit.attributes.get("logical_id", "")),
            source_file="kb.xlsx",
            document_title="FAQ",
            heading_path=("FAQ", "Registration"),
        )


class SuccessfulPipeline:
    def __init__(self) -> None:
        self.classify_calls: list[str] = []
        self.plan_calls: list[str] = []
        self.answer_calls: list[tuple[str, dict[str, object]]] = []

    def classify_query(self, query: str) -> QueryClassification:
        self.classify_calls.append(query)
        return QueryClassification(
            intent="enumeration",
            confidence=0.99,
            rationale=("Explicit request for program list/types",),
        )

    def plan_query(self, query: str) -> QueryPlan:
        self.plan_calls.append(query)
        classification = self.classify_query(query)
        scope_detection = QueryScopeDetection(
            primary_scope="programs",
            scopes=("programs",),
            confidence=0.95,
            rationale=("Program catalog or organized program terms",),
        )
        retrieval_plan = QueryRetrievalPlan(
            primary_query="організовані програми",
            alternate_queries=(),
            keywords=("організовані програми",),
            confidence=0.65,
            source="rules",
            rationale=("Using the raw query as the deterministic retrieval baseline.",),
        )
        policy_trace = QueryPolicyTrace(
            mode="fallback",
            llm_allowed_for=("classifier", "scope", "planner", "retrieval"),
            stage_toggles=QueryStageToggles(),
            rules_min_confidence=0.85,
            deterministic_classification=classification,
            deterministic_scope_detection=scope_detection,
            deterministic_strategy="enumeration_catalog",
            deterministic_retrieval_plan=retrieval_plan,
            final_intent_source="rules",
            final_scope_source="rules",
            final_strategy_source="rules",
            final_retrieval_source="rules",
            llm_requested=False,
            llm_used=False,
            llm_cache_hit=False,
            llm_skip_reason="deterministic_pipeline_sufficient",
        )
        return QueryPlan(
            classification=classification,
            scope_detection=scope_detection,
            strategy="enumeration_catalog",
            retrieval_plan=retrieval_plan,
            needs_retrieval=False,
            needs_structure=True,
            rationale=("Enumeration intent selects catalog/list strategy.",),
            strategy_source="rules",
            policy_trace=policy_trace,
        )

    def answer_query(self, query: str, **kwargs: object) -> QueryAnswerResult:
        self.answer_calls.append((query, kwargs))
        return QueryAnswerResult(
            plan=self.plan_query(query),
            summary="Знайшов такі організовані програми:",
            blocks=(AnswerBlock(title="Програми", lines=("Програма А", "Програма Б")),),
            sources=("programs",),
            search_response=None,
            fallback_used=False,
            retrieval_trace=QueryRetrievalExecutionTrace(
                initial_planned_queries=("РѕСЂРіР°РЅС–Р·РѕРІР°РЅС– РїСЂРѕРіСЂР°РјРё",),
                initial_executed_queries=(),
                initial_result_count=0,
                initial_top_score=None,
                initial_stop_reason="no_alternate_queries_planned",
                retry_executed=False,
                planned_queries=("організовані програми",),
                executed_queries=(),
                merged_raw_hit_count=0,
                merged_result_count=0,
                stop_reason="no_alternate_queries_planned",
                renderer_trusted_top_hit=True,
                renderer_note="structure_only_overview",
            ),
        )


class FailingPipeline:
    def classify_query(self, query: str) -> QueryClassification:
        raise RuntimeError("pipeline unavailable")

    def plan_query(self, query: str) -> QueryPlan:
        raise RuntimeError("pipeline unavailable")

    def answer_query(self, query: str, **kwargs: object) -> QueryAnswerResult:
        raise RuntimeError("pipeline unavailable")


def _command(command_name: str, args: str | None) -> CommandObject:
    return CommandObject(prefix="/", command=command_name, mention=None, args=args)


def _response_with_hit() -> SearchResponse:
    return SearchResponse(
        results=[
            SearchHit(
                file_id="file_1",
                filename="faq.md",
                score=0.83,
                attributes={"logical_id": "faq", "category": "faq"},
                text="First chunk\n\nSecond chunk",
            )
        ],
        top_score=0.83,
        used_threshold=0.7,
        fallback_triggered=False,
        fallback_message=None,
    )


PUBLIC_DEBUG_CONTEXT = {"debug_commands_mode": "public"}


def test_extract_query_text_trims_whitespace() -> None:
    assert extract_query_text(_command("vs", "   how to register?   ")) == "how to register?"
    assert extract_query_text(_command("vs", None)) == ""


def test_split_for_telegram_keeps_full_content_and_honors_limit() -> None:
    text = "line-1\nline-2\nline-3\nline-4"
    chunks = split_for_telegram(text, limit=10)

    assert "".join(chunks) == text
    assert all(len(chunk) <= 10 for chunk in chunks)


def test_format_search_messages_contains_raw_hit_data_and_context() -> None:
    rendered_messages = format_search_messages(
        "how to register?",
        _response_with_hit(),
        hit_contexts=[
            SearchHitDebugContext(
                logical_id="faq",
                source_file="kb.xlsx",
                document_title="FAQ",
                heading_path=("FAQ", "Registration"),
            )
        ],
    )

    assert len(rendered_messages) == 1
    rendered = rendered_messages[0]
    assert "Service:" in rendered
    assert "query=how to register?" in rendered
    assert "result=1/1" in rendered
    assert "score=0.8300" in rendered
    assert "file=faq.md" in rendered
    assert "logical_id=faq" in rendered
    assert "source=kb.xlsx" in rendered
    assert "heading_path=FAQ > Registration" in rendered
    assert "Text:\nFirst chunk\n\nSecond chunk" in rendered


def test_vs_handler_returns_usage_when_query_is_empty(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    monkeypatch.setattr(query_debug, "_create_retrieval_service", lambda: None)

    asyncio.run(
        query_debug.vector_search_handler(
            message,
            _command("vs", None),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    assert [call["text"] for call in bot.calls] == [VS_USAGE_TEXT]
    assert bot.calls[0]["parse_mode"] is None


def test_vs_handler_returns_raw_search_hits(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    service = SuccessfulRetrievalService(_response_with_hit())
    monkeypatch.setattr(query_debug, "_create_retrieval_service", lambda: service)
    monkeypatch.setattr(query_debug, "_create_structure_reader", lambda: FakeStructureReader())

    asyncio.run(
        query_debug.vector_search_handler(
            message,
            _command("vs", "how to register?"),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    assert service.calls == [{"query": "how to register?", "rewrite_query": False}]
    rendered = "".join(str(call["text"]) for call in bot.calls)
    assert "Service:" in rendered
    assert "query=how to register?" in rendered
    assert "score=0.8300" in rendered
    assert "file=faq.md" in rendered
    assert "heading_path=FAQ > Registration" in rendered
    assert "Text:\nFirst chunk\n\nSecond chunk" in rendered
    assert "answer_mode=" not in rendered
    assert all(call["parse_mode"] is None for call in bot.calls)


def test_vs_handler_returns_friendly_error_when_search_fails(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    monkeypatch.setattr(query_debug, "_create_retrieval_service", lambda: FailingRetrievalService())

    asyncio.run(
        query_debug.vector_search_handler(
            message,
            _command("vs", "how to register?"),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    assert [call["text"] for call in bot.calls] == [query_debug.VS_ERROR_TEXT]
    assert bot.calls[0]["parse_mode"] is None


def test_qclass_handler_renders_intent_rules(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    pipeline = SuccessfulPipeline()
    monkeypatch.setattr(query_debug, "_create_query_pipeline", lambda: pipeline)

    asyncio.run(
        query_debug.query_classification_handler(
            message,
            _command(query_debug.QCLASS_COMMAND_NAME, "Які є види організованих програм?"),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    rendered = "".join(str(call["text"]) for call in bot.calls)
    assert "intent=enumeration" in rendered
    assert "confidence=0.99" in rendered
    assert "Matched rules:" in rendered
    assert "Explicit request for program list/types" in rendered


def test_qplan_handler_renders_scope_strategy_and_retrieval_plan(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    pipeline = SuccessfulPipeline()
    monkeypatch.setattr(query_debug, "_create_query_pipeline", lambda: pipeline)

    asyncio.run(
        query_debug.query_plan_handler(
            message,
            _command(query_debug.QPLAN_COMMAND_NAME, "Які є види організованих програм?"),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    rendered = "".join(str(call["text"]) for call in bot.calls)
    assert "intent=enumeration" in rendered
    assert "scope=programs" in rendered
    assert "strategy=enumeration_catalog" in rendered
    assert "retrieval_source=rules" in rendered
    assert "Retrieval plan:" in rendered
    assert "primary_query=організовані програми" in rendered
    assert "needs_retrieval=False" in rendered
    assert "needs_structure=True" in rendered
    assert "Policy trace:" in rendered
    assert "mode=fallback" in rendered
    assert "llm_requested=False" in rendered


def test_qroute_handler_renders_policy_trace(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    pipeline = SuccessfulPipeline()
    monkeypatch.setattr(query_debug, "_create_query_pipeline", lambda: pipeline)

    asyncio.run(
        query_debug.query_route_handler(
            message,
            _command(query_debug.QROUTE_COMMAND_NAME, "Які є види організованих програм?"),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    rendered = "".join(str(call["text"]) for call in bot.calls)
    assert "mode=fallback" in rendered
    assert "llm_used=False" in rendered
    assert "llm_escalation_triggered=False" in rendered
    assert "retry_executed=False" in rendered
    assert "deterministic_strategy=enumeration_catalog" in rendered
    assert "deterministic_retrieval_primary=організовані програми" in rendered
    assert "final_retrieval_source=rules" in rendered
    assert "Stage toggles:" in rendered


def test_qanswer_handler_runs_structured_pipeline(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    pipeline = SuccessfulPipeline()
    monkeypatch.setattr(query_debug, "_create_query_pipeline", lambda: pipeline)

    asyncio.run(
        query_debug.query_answer_handler(
            message,
            _command(query_debug.QANSWER_COMMAND_NAME, "Які є види організованих програм?"),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    assert pipeline.answer_calls == [
        ("Які є види організованих програм?", {"rewrite_query": False})
    ]
    rendered = "".join(str(call["text"]) for call in bot.calls)
    assert "intent=enumeration" in rendered
    assert "strategy=enumeration_catalog" in rendered
    assert "strategy_source=rules" in rendered
    assert "retrieval_source=rules" in rendered
    assert "mode=fallback" in rendered
    assert "Retrieval plan:" in rendered
    assert "Знайшов такі організовані програми:" in rendered
    assert "- Програма А" in rendered
    assert "Sources:\n- programs" in rendered


def test_qretrieve_handler_renders_retrieval_plan_and_trace(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    pipeline = SuccessfulPipeline()
    monkeypatch.setattr(query_debug, "_create_query_pipeline", lambda: pipeline)

    asyncio.run(
        query_debug.query_retrieval_handler(
            message,
            _command(query_debug.QRETRIEVE_COMMAND_NAME, "Які є види організованих програм?"),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    rendered = "".join(str(call["text"]) for call in bot.calls)
    assert "retrieval_source=rules" in rendered
    assert "Retrieval plan:" in rendered
    assert "Retrieval execution:" in rendered
    assert "planned_queries=організовані програми" in rendered
    assert "stop_reason=no_alternate_queries_planned" in rendered


def test_qdebug_handlers_return_friendly_error_when_pipeline_fails(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    monkeypatch.setattr(query_debug, "_create_query_pipeline", lambda: FailingPipeline())

    asyncio.run(
        query_debug.query_classification_handler(
            message,
            _command(query_debug.QCLASS_COMMAND_NAME, "Що ви можете мені запропонувати?"),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    assert [call["text"] for call in bot.calls] == [query_debug.QDEBUG_ERROR_TEXT]
    assert bot.calls[0]["parse_mode"] is None


def test_debug_commands_disabled_mode_blocks_debug_requests(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    service = SuccessfulRetrievalService(_response_with_hit())
    monkeypatch.setattr(query_debug, "_create_retrieval_service", lambda: service)

    asyncio.run(
        query_debug.vector_search_handler(
            message,
            _command("vs", "how to register?"),
            debug_commands_mode="disabled",
            admin_user_ids={1001},
        )
    )

    assert service.calls == []
    assert [call["text"] for call in bot.calls] == [query_debug.QDEBUG_DISABLED_TEXT]


def test_debug_commands_admin_mode_blocks_non_admin_user(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot, user_id=5555)
    service = SuccessfulRetrievalService(_response_with_hit())
    monkeypatch.setattr(query_debug, "_create_retrieval_service", lambda: service)

    asyncio.run(
        query_debug.vector_search_handler(
            message,
            _command("vs", "how to register?"),
            debug_commands_mode="admins",
            admin_user_ids={1001},
        )
    )

    assert service.calls == []
    assert [call["text"] for call in bot.calls] == [query_debug.QDEBUG_ADMIN_ONLY_TEXT]


def test_debug_commands_admin_mode_allows_admin_user(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot, user_id=1001)
    service = SuccessfulRetrievalService(_response_with_hit())
    monkeypatch.setattr(query_debug, "_create_retrieval_service", lambda: service)
    monkeypatch.setattr(query_debug, "_create_structure_reader", lambda: FakeStructureReader())

    asyncio.run(
        query_debug.vector_search_handler(
            message,
            _command("vs", "how to register?"),
            debug_commands_mode="admins",
            admin_user_ids={1001},
        )
    )

    assert service.calls == [{"query": "how to register?", "rewrite_query": False}]
    rendered = "".join(str(call["text"]) for call in bot.calls)
    assert "query=how to register?" in rendered
