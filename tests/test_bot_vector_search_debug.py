from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram.filters import CommandObject

from app.bot.handlers import scenarios
from app.bot.handlers.vector_search_debug import (
    VS_ERROR_TEXT,
    VS_USAGE_TEXT,
    extract_query_text,
    format_search_messages,
    split_for_telegram,
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
    def __init__(self, bot: FakeBot) -> None:
        self.from_user = SimpleNamespace(id=1001)
        self.chat = SimpleNamespace(id=2002)
        self.bot = bot


class SuccessfulService:
    def __init__(self, response: SearchResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> SearchResponse:
        self.calls.append(kwargs)
        return self.response


class FailingService:
    def search(self, **kwargs: object) -> SearchResponse:
        raise RuntimeError("search backend unavailable")


def _command(args: str | None) -> CommandObject:
    return CommandObject(prefix="/", command="vs", mention=None, args=args)


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


def test_extract_query_text_trims_whitespace() -> None:
    assert extract_query_text(_command("   how to register?   ")) == "how to register?"
    assert extract_query_text(_command(None)) == ""


def test_split_for_telegram_keeps_full_content_and_honors_limit() -> None:
    text = "line-1\nline-2\nline-3\nline-4"
    chunks = split_for_telegram(text, limit=10)

    assert "".join(chunks) == text
    assert all(len(chunk) <= 10 for chunk in chunks)


def test_format_search_messages_contains_two_blocks_and_full_text() -> None:
    rendered_messages = format_search_messages("how to register?", _response_with_hit())

    assert len(rendered_messages) == 1
    rendered = rendered_messages[0]
    assert "Service:" in rendered
    assert "query=how to register?" in rendered
    assert "result=1/1" in rendered
    assert "score=0.8300" in rendered
    assert "file=faq.md" in rendered
    assert "logical_id=faq" in rendered
    assert "category=faq" in rendered
    assert "--------------------" in rendered
    assert "Text:\nFirst chunk\n\nSecond chunk" in rendered


def test_format_search_messages_renders_fallback_block() -> None:
    response = SearchResponse(
        results=[],
        top_score=None,
        used_threshold=0.7,
        fallback_triggered=True,
        fallback_message="No relevant information found in the knowledge base.",
    )

    rendered_messages = format_search_messages("unknown topic", response)

    assert len(rendered_messages) == 1
    rendered = rendered_messages[0]
    assert "Service:" in rendered
    assert "result_count=0" in rendered
    assert "fallback_triggered=True" in rendered
    assert "Text:\nNo relevant information found in the knowledge base." in rendered


def test_vs_handler_returns_usage_when_query_is_empty(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    monkeypatch.setattr(scenarios, "_create_retrieval_service", lambda: None)

    asyncio.run(scenarios.vector_search_handler(message, _command(None)))

    assert [call["text"] for call in bot.calls] == [VS_USAGE_TEXT]
    assert bot.calls[0]["parse_mode"] is None


def test_vs_handler_returns_formatted_search_hits(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    service = SuccessfulService(_response_with_hit())
    monkeypatch.setattr(scenarios, "_create_retrieval_service", lambda: service)

    asyncio.run(scenarios.vector_search_handler(message, _command("how to register?")))

    assert service.calls == [{"query": "how to register?", "rewrite_query": False}]
    rendered = "".join(str(call["text"]) for call in bot.calls)
    assert "Service:" in rendered
    assert "query=how to register?" in rendered
    assert "score=0.8300" in rendered
    assert "logical_id=faq" in rendered
    assert "category=faq" in rendered
    assert "Text:\nFirst chunk\n\nSecond chunk" in rendered
    assert all(call["parse_mode"] is None for call in bot.calls)


def test_vs_handler_returns_friendly_error_when_search_fails(monkeypatch) -> None:
    bot = FakeBot()
    message = FakeMessage(bot)
    monkeypatch.setattr(scenarios, "_create_retrieval_service", lambda: FailingService())

    asyncio.run(scenarios.vector_search_handler(message, _command("how to register?")))

    assert [call["text"] for call in bot.calls] == [VS_ERROR_TEXT]
    assert bot.calls[0]["parse_mode"] is None
