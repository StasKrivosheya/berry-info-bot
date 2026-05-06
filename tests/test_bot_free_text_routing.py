from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.bot.handlers import scenarios
from app.bot.scenarios.catalog import MENU_MESSAGE_TEXT, UNKNOWN_TEXT_RESPONSE
from app.services.knowledge_base.query_router import QueryRoute, QueryRoutingResult


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.chat_actions: list[dict[str, object]] = []

    async def send_message(self, *, chat_id: int, text: str, reply_markup=None) -> SimpleNamespace:
        self.calls.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )
        return SimpleNamespace(message_id=len(self.calls))

    async def send_chat_action(self, *, chat_id: int, action: str) -> None:
        self.chat_actions.append({"chat_id": chat_id, "action": action})

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
    to_thread_calls: list[str] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        to_thread_calls.append(func.__name__)
        return func(*args, **kwargs)

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
    monkeypatch.setattr(scenarios.asyncio, "to_thread", fake_to_thread)

    asyncio.run(scenarios.unknown_text_handler(FakeMessage(bot, "Привіт")))

    assert captured == [{"chat_id": 2002, "user_id": 1001, "text": "Привіт"}]
    assert to_thread_calls == ["fake_route_free_text"]
    assert bot.chat_actions == [{"chat_id": 2002, "action": "typing"}]
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
    to_thread_calls: list[str] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        to_thread_calls.append(func.__name__)
        return func(*args, **kwargs)

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
    monkeypatch.setattr(scenarios.asyncio, "to_thread", fake_to_thread)

    asyncio.run(scenarios.unknown_text_handler(FakeMessage(bot, "Які є програми?")))

    assert to_thread_calls == ["<lambda>", "fake_answer"]
    assert bot.chat_actions == [{"chat_id": 2002, "action": "typing"}]
    assert answered == [route]
    assert [call["text"] for call in bot.calls] == ["Є програми для дітей."]
    assert bot.calls[0]["reply_markup"] is not None


def test_dynamic_rag_answer_is_sent_as_plain_text(monkeypatch) -> None:
    bot = FakeBot()
    answer_text = "<b>price</b> 100 uah"
    route = QueryRoute(
        route="kb_query",
        original_message="price?",
        canonical_question_uk="price?",
        vector_query_uk="price?",
        lexical_keywords=["price"],
        lexical_phrases=["price"],
        confidence=0.93,
    )

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(
        scenarios,
        "_route_free_text_for_message",
        lambda **kwargs: QueryRoutingResult(route=route, response_text="", should_search=True),
    )
    monkeypatch.setattr(scenarios, "_answer_searchable_route", lambda route: answer_text)
    monkeypatch.setattr(scenarios.asyncio, "to_thread", fake_to_thread)

    asyncio.run(scenarios.unknown_text_handler(FakeMessage(bot, "price?")))

    assert bot.calls[0]["text"] == answer_text
    assert "parse_mode" not in bot.calls[0]


def test_free_text_handler_refreshes_typing_until_answer(monkeypatch) -> None:
    bot = FakeBot()
    sleep_calls: list[float] = []
    original_sleep = scenarios.asyncio.sleep

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) == 1:
            return
        await original_sleep(0)

    async def fake_to_thread(func, /, *args, **kwargs):
        await original_sleep(0)
        return func(*args, **kwargs)

    monkeypatch.setattr(scenarios, "TELEGRAM_TYPING_REFRESH_SECONDS", 0.01)
    monkeypatch.setattr(scenarios.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(scenarios.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(
        scenarios,
        "_route_free_text_for_message",
        lambda **kwargs: QueryRoutingResult(
            route=QueryRoute(
                route="greeting",
                original_message=str(kwargs["text"]),
                confidence=0.96,
            ),
            response_text="service text",
            should_search=False,
        ),
    )

    asyncio.run(scenarios.unknown_text_handler(FakeMessage(bot, "Привіт")))

    assert bot.chat_actions == [
        {"chat_id": 2002, "action": "typing"},
        {"chat_id": 2002, "action": "typing"},
    ]
    assert sleep_calls == [0.01, 0.01]
    assert [call["text"] for call in bot.calls] == ["service text"]


def test_unknown_command_does_not_use_llm_router(monkeypatch) -> None:
    bot = FakeBot()

    def fail_if_called(**kwargs: object) -> QueryRoutingResult:
        raise AssertionError("LLM router should not be called for Telegram commands.")

    monkeypatch.setattr(scenarios, "_route_free_text_for_message", fail_if_called)

    asyncio.run(scenarios.unknown_command_handler(FakeMessage(bot, "/unknown")))

    assert [call["text"] for call in bot.calls] == [UNKNOWN_TEXT_RESPONSE]
