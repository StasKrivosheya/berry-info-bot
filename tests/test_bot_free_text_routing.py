from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.bot.handlers import scenarios
from app.bot.scenarios.catalog import MENU_MESSAGE_TEXT, UNKNOWN_TEXT_RESPONSE
from app.services.knowledge_base.query_router import QueryRoute, QueryRoutingResult


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send_message(self, *, chat_id: int, text: str, reply_markup=None) -> SimpleNamespace:
        self.calls.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )
        return SimpleNamespace(message_id=len(self.calls))

    async def edit_message_reply_markup(self, **kwargs: object) -> None:
        return None


class FakeMessage:
    def __init__(self, bot: FakeBot, text: str) -> None:
        self.from_user = SimpleNamespace(id=1001)
        self.chat = SimpleNamespace(id=2002)
        self.bot = bot
        self.text = text


def test_free_text_handler_uses_structured_route_contract(monkeypatch) -> None:
    bot = FakeBot()
    captured: list[dict[str, object]] = []

    def fake_route_free_text(*, chat_id: int, user_id: int, text: str) -> QueryRoutingResult:
        captured.append({"chat_id": chat_id, "user_id": user_id, "text": text})
        return QueryRoutingResult(
            route=QueryRoute(
                route="greeting",
                original_message=text,
                confidence=0.96,
            ),
            response_text="service text",
            should_search=False,
        )

    monkeypatch.setattr(scenarios, "_route_free_text_for_message", fake_route_free_text)

    asyncio.run(scenarios.unknown_text_handler(FakeMessage(bot, "Привіт")))

    assert captured == [{"chat_id": 2002, "user_id": 1001, "text": "Привіт"}]
    assert [call["text"] for call in bot.calls] == ["service text"]
    assert bot.calls[0]["reply_markup"] is not None


def test_menu_help_route_shows_main_menu(monkeypatch) -> None:
    bot = FakeBot()

    monkeypatch.setattr(
        scenarios,
        "_route_free_text_for_message",
        lambda **kwargs: QueryRoutingResult(
            route=QueryRoute(
                route="menu_help",
                original_message=str(kwargs["text"]),
                confidence=0.91,
            ),
            response_text="",
            should_search=False,
        ),
    )

    asyncio.run(scenarios.unknown_text_handler(FakeMessage(bot, "Покажи меню")))

    assert [call["text"] for call in bot.calls] == [MENU_MESSAGE_TEXT]
    assert bot.calls[0]["reply_markup"] is not None


def test_kb_query_route_uses_answer_generation(monkeypatch) -> None:
    bot = FakeBot()
    route = QueryRoute(
        route="kb_query",
        original_message="Які є програми?",
        canonical_question_uk="Які програми є у Berry Land?",  # noqa: RUF001
        vector_query_uk="програми Berry Land",
        lexical_keywords=["програми"],
        lexical_phrases=["програми Berry Land"],
        confidence=0.93,
    )
    answered: list[QueryRoute] = []

    monkeypatch.setattr(
        scenarios,
        "_route_free_text_for_message",
        lambda **kwargs: QueryRoutingResult(
            route=route,
            response_text="service text",
            should_search=True,
        ),
    )

    def fake_answer(search_route: QueryRoute) -> str:
        answered.append(search_route)
        return "Є програми для дітей."

    monkeypatch.setattr(scenarios, "_answer_searchable_route", fake_answer)

    asyncio.run(scenarios.unknown_text_handler(FakeMessage(bot, "Які є програми?")))

    assert answered == [route]
    assert [call["text"] for call in bot.calls] == ["Є програми для дітей."]
    assert bot.calls[0]["reply_markup"] is not None


def test_unknown_command_does_not_use_llm_router(monkeypatch) -> None:
    bot = FakeBot()

    def fail_if_called(**kwargs: object) -> QueryRoutingResult:
        raise AssertionError("LLM router should not be called for Telegram commands.")

    monkeypatch.setattr(scenarios, "_route_free_text_for_message", fail_if_called)

    asyncio.run(scenarios.unknown_command_handler(FakeMessage(bot, "/unknown")))

    assert [call["text"] for call in bot.calls] == [UNKNOWN_TEXT_RESPONSE]
