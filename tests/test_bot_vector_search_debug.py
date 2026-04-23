
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from aiogram.filters import CommandObject

from app.bot.handlers.debug import query_debug
from app.bot.handlers.debug.vector_search_debug import (
    VS_USAGE_TEXT,
    extract_query_text,
    format_search_messages,
    split_for_telegram,
)
from app.services.knowledge_base.query.dto import (
    AnswerResult,
    NormalizedQuery,
    RewriteResult,
    RouterDecision,
)
from app.services.knowledge_base.query.types import (
    QueryClassification,
    QueryInspectionResult,
    QueryPolicyTrace,
    QueryRetrievalExecutionTrace,
    QueryRetrievalPlan,
    QueryRouteContext,
    QueryScopeDetection,
    QueryStageToggles,
    RuleMatch,
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
        self.inspect_calls: list[tuple[str, dict[str, object]]] = []
        self._classification = QueryClassification(
            intent="enumeration",
            confidence=0.99,
            matched_rules=(
                RuleMatch(
                    rule_id="enumeration_program_types",
                    priority=100,
                    description="Program list request",
                    evidence=("program list",),
                ),
            ),
            rationale=("Explicit request for program list/types",),
        )
        self._scope_detection = QueryScopeDetection(
            primary_scope="programs",
            scopes=("programs",),
            confidence=0.95,
            matched_rules=(
                RuleMatch(
                    rule_id="scope_programs",
                    priority=90,
                    description="Program-focused scope",
                    evidence=("program",),
                ),
            ),
            rationale=("Program catalog or organized program terms",),
        )
        self._retrieval_plan = QueryRetrievalPlan(
            primary_query="organized programs",
            alternate_queries=(),
            keywords=("organized programs",),
            confidence=0.65,
            source="rules",
            rationale=("Using the raw query as the deterministic retrieval baseline.",),
        )
        self._policy_trace = QueryPolicyTrace(
            mode="fallback",
            llm_allowed_for=("classifier", "scope", "planner", "retrieval"),
            stage_toggles=QueryStageToggles(),
            rules_min_confidence=0.85,
            deterministic_classification=self._classification,
            deterministic_scope_detection=self._scope_detection,
            deterministic_strategy="enumeration_catalog",
            deterministic_retrieval_plan=self._retrieval_plan,
            final_intent_source="rules",
            final_scope_source="rules",
            final_strategy_source="rules",
            final_retrieval_source="rules",
            llm_requested=False,
            llm_used=False,
            llm_cache_hit=False,
            llm_skip_reason="deterministic_pipeline_sufficient",
        )

    def classify_query(self, query: str) -> QueryClassification:
        self.classify_calls.append(query)
        return self._classification

    def inspect_query(self, query: str, **kwargs: object) -> QueryInspectionResult:
        self.inspect_calls.append((query, kwargs))
        route_context = QueryRouteContext(
            classification=self._classification,
            scope_detection=self._scope_detection,
            strategy="enumeration_catalog",
            retrieval_plan=self._retrieval_plan,
            needs_retrieval=False,
            needs_structure=True,
            rationale=("Enumeration intent selects catalog/list strategy.",),
            strategy_source="rules",
            policy_trace=self._policy_trace,
        )
        return QueryInspectionResult(
            normalized_query=NormalizedQuery(
                raw_text=query,
                user_locale="uk-UA",
                detected_language="uk",
                canonical_uk=query.casefold(),
                created_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
            ),
            route_context=route_context,
            router_decision=RouterDecision(
                intent="enumeration",
                needs_clarification=False,
                clarification_question=None,
                missing_slots=(),
                routing_flags={
                    "scope": "programs",
                    "scopes": ("programs",),
                    "strategy": "enumeration_catalog",
                    "needs_retrieval": False,
                    "needs_structure": True,
                    "policy_mode": "fallback",
                    "intent_source": "rules",
                    "scope_source": "rules",
                    "strategy_source": "rules",
                    "retrieval_source": "rules",
                },
            ),
            rewrite_result=RewriteResult(
                canonical_uk=query.casefold(),
                vector_query_uk="organized programs",
                lexical={
                    "keywords": ("organized programs",),
                    "synonyms": (),
                    "phrases": (query.casefold(), "organized programs"),
                },
                filters={
                    "category": None,
                    "logical_id": None,
                    "language": "uk",
                    "attribute_filters": {},
                },
            ),
            answer_result=AnswerResult(
                state="answered",
                answer_text=(
                    "Found these organized programs:\n\n"
                    "Programs\n"
                    "- Program A\n"
                    "- Program B\n\n"
                    "Sources:\n"
                    "- programs"
                ),
                clarification_question=None,
                source_section_ids=("programs",),
                debug_reason="structure_only_overview",
            ),
            retrieval_trace=QueryRetrievalExecutionTrace(
                initial_planned_queries=("organized programs",),
                initial_executed_queries=(),
                initial_result_count=0,
                initial_top_score=None,
                initial_stop_reason="no_alternate_queries_planned",
                retry_executed=False,
                planned_queries=("organized programs",),
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

    def inspect_query(self, query: str, **kwargs: object) -> QueryInspectionResult:
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
            _command(query_debug.QCLASS_COMMAND_NAME, "What organized programs do you have?"),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    rendered = "".join(str(call["text"]) for call in bot.calls)
    assert "intent=enumeration" in rendered
    assert "confidence=0.99" in rendered
    assert "Matched rules:" in rendered
    assert "Explicit request for program list/types" in rendered


def test_qplan_handler_renders_scope_strategy_and_rewrite(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    pipeline = SuccessfulPipeline()
    monkeypatch.setattr(query_debug, "_create_query_pipeline", lambda: pipeline)

    asyncio.run(
        query_debug.query_plan_handler(
            message,
            _command(query_debug.QPLAN_COMMAND_NAME, "What organized programs do you have?"),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    rendered = "".join(str(call["text"]) for call in bot.calls)
    assert "intent=enumeration" in rendered
    assert "scope=programs" in rendered
    assert "strategy=enumeration_catalog" in rendered
    assert "needs_retrieval=False" in rendered
    assert "needs_structure=True" in rendered
    assert "Rewrite result:" in rendered
    assert "vector_query_uk=organized programs" in rendered
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
            _command(query_debug.QROUTE_COMMAND_NAME, "What organized programs do you have?"),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    rendered = "".join(str(call["text"]) for call in bot.calls)
    assert "mode=fallback" in rendered
    assert "llm_used=False" in rendered
    assert "llm_escalation_triggered=False" in rendered
    assert "retry_executed=False" in rendered
    assert "deterministic_strategy=enumeration_catalog" in rendered
    assert "deterministic_retrieval_primary=organized programs" in rendered
    assert "final_retrieval_source=rules" in rendered
    assert "Stage toggles:" in rendered


def test_qanswer_handler_renders_answer_result(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    pipeline = SuccessfulPipeline()
    monkeypatch.setattr(query_debug, "_create_query_pipeline", lambda: pipeline)

    asyncio.run(
        query_debug.query_answer_handler(
            message,
            _command(query_debug.QANSWER_COMMAND_NAME, "What organized programs do you have?"),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    assert pipeline.inspect_calls == [
        ("What organized programs do you have?", {"rewrite_query": False})
    ]
    rendered = "".join(str(call["text"]) for call in bot.calls)
    assert "intent=enumeration" in rendered
    assert "strategy=enumeration_catalog" in rendered
    assert "answer_state=answered" in rendered
    assert "source_count=1" in rendered
    assert "Found these organized programs:" in rendered
    assert "- Program A" in rendered
    assert "Sources:\n- programs" in rendered


def test_qretrieve_handler_renders_retrieval_trace(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    pipeline = SuccessfulPipeline()
    monkeypatch.setattr(query_debug, "_create_query_pipeline", lambda: pipeline)

    asyncio.run(
        query_debug.query_retrieval_handler(
            message,
            _command(query_debug.QRETRIEVE_COMMAND_NAME, "What organized programs do you have?"),
            **PUBLIC_DEBUG_CONTEXT,
        )
    )

    rendered = "".join(str(call["text"]) for call in bot.calls)
    assert "retrieval_source=rules" in rendered
    assert "Retrieval execution:" in rendered
    assert "final_planned_queries=organized programs" in rendered
    assert "stop_reason=no_alternate_queries_planned" in rendered


def test_qdebug_handlers_return_friendly_error_when_pipeline_fails(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    monkeypatch.setattr(query_debug, "_create_query_pipeline", lambda: FailingPipeline())

    asyncio.run(
        query_debug.query_classification_handler(
            message,
            _command(query_debug.QCLASS_COMMAND_NAME, "What can you offer me?"),
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
