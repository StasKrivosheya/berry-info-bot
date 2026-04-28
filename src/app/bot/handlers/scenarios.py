from __future__ import annotations

import logging
import time
from functools import lru_cache

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot.scenarios.callbacks import NAV_ACTION_BACK, NAV_ACTION_OPEN, ScenarioNavCallback
from app.bot.scenarios.catalog import (
    KEYWORD_2026_RESPONSE,
    KEYWORD_2026_TEXT,
    MAIN_MENU_ACTIONS,
    MAIN_MENU_BACK_TARGET,
    MENU_MESSAGE_TEXT,
    MISSING_NODE_RESPONSE,
    UNKNOWN_MESSAGE_TYPE_RESPONSE,
    UNKNOWN_TEXT_RESPONSE,
    get_node,
)
from app.bot.scenarios.keyboards import build_main_menu_keyboard, build_scenario_keyboard
from app.bot.scenarios.navigation import ScenarioMessenger, resolve_chat_id
from app.core.config import get_settings
from app.services.knowledge_base.answer_generator import (
    FIXED_NOT_FOUND_FALLBACK,
    OpenAIGroundedAnswerGenerator,
    fallback_answer,
)
from app.services.knowledge_base.query_router import (
    SERVICE_FALLBACK_TEXT,
    OpenAIQueryRouter,
    QueryContextKey,
    QueryContextStore,
    QueryRoutingResult,
    route_free_text_message,
)
from app.services.knowledge_base.retrieval import HybridSearchService

logger = logging.getLogger(__name__)

router = Router(name="scenarios")
messenger = ScenarioMessenger()
LOG_EVENT_KB_ANSWERED = "bot_kb_answered"


@router.message(CommandStart())
@router.message(Command("menu"))
async def show_main_menu(message: Message) -> None:
    """Show top-level menu entry points."""

    if message.from_user is None:
        return

    await messenger.send(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=MENU_MESSAGE_TEXT,
        reply_markup=build_main_menu_keyboard(),
    )


@router.message(F.text.in_(MAIN_MENU_ACTIONS.keys()))
async def open_top_level_section(message: Message) -> None:
    """Open first-level scenario node by menu button text."""

    if message.from_user is None or message.text is None:
        return

    node_id = MAIN_MENU_ACTIONS[message.text]
    node = get_node(node_id)
    if node is None:
        await messenger.send(
            bot=message.bot,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            text=MISSING_NODE_RESPONSE,
            reply_markup=build_main_menu_keyboard(),
        )
        return

    await messenger.send(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=node.text,
        reply_markup=build_scenario_keyboard(node),
    )


@router.callback_query(ScenarioNavCallback.filter(F.action == NAV_ACTION_OPEN))
async def open_scenario_step(
    callback: CallbackQuery,
    callback_data: ScenarioNavCallback,
) -> None:
    """Open child node from inline button."""

    chat_id = resolve_chat_id(callback.message)
    if callback.from_user is None or chat_id is None:
        await callback.answer()
        return

    node = get_node(callback_data.node_id)
    if node is None:
        await callback.answer(MISSING_NODE_RESPONSE)
        return

    await callback.answer()
    await messenger.send(
        bot=callback.bot,
        chat_id=chat_id,
        user_id=callback.from_user.id,
        text=node.text,
        reply_markup=build_scenario_keyboard(node),
    )


@router.callback_query(ScenarioNavCallback.filter(F.action == NAV_ACTION_BACK))
async def navigate_back(
    callback: CallbackQuery,
    callback_data: ScenarioNavCallback,
) -> None:
    """Go one level up according to scenario parent chain."""

    chat_id = resolve_chat_id(callback.message)
    if callback.from_user is None or chat_id is None:
        await callback.answer()
        return

    await callback.answer()

    if callback_data.node_id == MAIN_MENU_BACK_TARGET:
        await messenger.send(
            bot=callback.bot,
            chat_id=chat_id,
            user_id=callback.from_user.id,
            text=MENU_MESSAGE_TEXT,
            reply_markup=build_main_menu_keyboard(),
        )
        return

    node = get_node(callback_data.node_id)
    if node is None:
        await messenger.send(
            bot=callback.bot,
            chat_id=chat_id,
            user_id=callback.from_user.id,
            text=MISSING_NODE_RESPONSE,
            reply_markup=build_main_menu_keyboard(),
        )
        return

    await messenger.send(
        bot=callback.bot,
        chat_id=chat_id,
        user_id=callback.from_user.id,
        text=node.text,
        reply_markup=build_scenario_keyboard(node),
    )


@router.message(F.text == KEYWORD_2026_TEXT)
async def keyword_2026_handler(message: Message) -> None:
    """Return dedicated placeholder for special word 2026."""

    if message.from_user is None:
        return

    await messenger.send(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=KEYWORD_2026_RESPONSE,
        reply_markup=build_main_menu_keyboard(),
    )


@router.message(F.text.startswith("/"))
async def unknown_command_handler(message: Message) -> None:
    """Handle unsupported commands without invoking the LLM router."""

    if message.from_user is None:
        return

    await messenger.send(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=UNKNOWN_TEXT_RESPONSE,
        reply_markup=build_main_menu_keyboard(),
    )


@router.message(~F.text)
async def unknown_message_type_handler(message: Message) -> None:
    """Handle non-text content with a friendly placeholder response."""

    if message.from_user is None:
        return

    await messenger.send(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=UNKNOWN_MESSAGE_TYPE_RESPONSE,
        reply_markup=build_main_menu_keyboard(),
    )


@router.message(F.text)
async def unknown_text_handler(message: Message) -> None:
    """Route normal free text through the production KB routing contract."""

    if message.from_user is None or message.text is None:
        return

    routing_result = _route_free_text_for_message(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=message.text,
    )
    if routing_result.route is not None and routing_result.route.route == "menu_help":
        text = MENU_MESSAGE_TEXT
    elif routing_result.should_search and routing_result.route is not None:
        text = _answer_searchable_route(routing_result.route)
    else:
        text = routing_result.response_text

    await messenger.send(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=text,
        reply_markup=build_main_menu_keyboard(),
    )


@lru_cache(maxsize=1)
def _create_query_router() -> OpenAIQueryRouter:
    settings = get_settings()
    api_key = settings.openai_api_key_value
    model = settings.openai_query_router_model
    if api_key is None or model is None:
        msg = "query_router_unavailable:missing_openai_api_key_or_model"
        raise RuntimeError(msg)
    return OpenAIQueryRouter(
        api_key=api_key,
        model=model,
        timeout_seconds=settings.openai_query_router_timeout_seconds,
    )


@lru_cache(maxsize=1)
def _create_query_context_store() -> QueryContextStore:
    settings = get_settings()
    return QueryContextStore(ttl_seconds=settings.query_context_ttl_seconds)


@lru_cache(maxsize=1)
def _create_hybrid_search_service() -> HybridSearchService:
    return HybridSearchService()


@lru_cache(maxsize=1)
def _create_answer_generator() -> OpenAIGroundedAnswerGenerator:
    settings = get_settings()
    api_key = settings.openai_api_key_value
    model = settings.openai_answer_model
    if api_key is None or model is None:
        msg = "answer_generator_unavailable:missing_openai_api_key_or_model"
        raise RuntimeError(msg)
    return OpenAIGroundedAnswerGenerator(
        api_key=api_key,
        model=model,
        timeout_seconds=settings.openai_answer_timeout_seconds,
    )


def _route_free_text_for_message(*, chat_id: int, user_id: int, text: str) -> QueryRoutingResult:
    try:
        query_router = _create_query_router()
    except Exception:
        return QueryRoutingResult(
            route=None,
            response_text=SERVICE_FALLBACK_TEXT,
            should_search=False,
        )

    return route_free_text_message(
        router=query_router,
        context_store=_create_query_context_store(),
        context_key=QueryContextKey(chat_id=chat_id, user_id=user_id),
        message=text,
    )


def _answer_searchable_route(route) -> str:
    started_at = time.perf_counter()
    vector_count = 0
    lexical_count = 0
    answer_result = fallback_answer()
    try:
        search_result = _create_hybrid_search_service().search(route)
        vector_count = search_result.vector_result_count
        lexical_count = search_result.lexical_result_count
        answer_result = _create_answer_generator().answer(
            route=route,
            candidates=search_result.candidates,
        )
        return answer_result.answer_text
    except Exception:
        logger.warning("bot_kb_answer_failed", exc_info=True)
        return FIXED_NOT_FOUND_FALLBACK
    finally:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        logger.info(
            (
                "%s route=%s topic_hint=%s direction_hint=%s canonical_question=%r "
                "vector_candidate_count=%s "
                "lexical_candidate_count=%s accepted_candidate_ids=%s answer_state=%s "
                "elapsed_ms=%s"
            ),
            LOG_EVENT_KB_ANSWERED,
            route.route,
            route.topic_hint,
            route.direction_hint,
            route.canonical_question_uk,
            vector_count,
            lexical_count,
            ",".join(answer_result.accepted_candidate_ids),
            answer_result.answer_state,
            elapsed_ms,
        )
