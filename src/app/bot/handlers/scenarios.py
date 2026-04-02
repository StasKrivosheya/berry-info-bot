from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.vector_search_debug import (
    VS_COMMAND_NAME,
    VS_ERROR_TEXT,
    VS_USAGE_TEXT,
    extract_query_text,
    format_search_messages,
    split_for_telegram,
)
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
from app.services.knowledge_base.retrieval import KnowledgeBaseRetrievalService

router = Router(name="scenarios")
messenger = ScenarioMessenger()
logger = logging.getLogger(__name__)

LOG_EVENT_BOT_VS_SEARCH_FAILED = "bot_vs_search_failed"


def _create_retrieval_service() -> KnowledgeBaseRetrievalService:
    return KnowledgeBaseRetrievalService()


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


@router.message(Command(VS_COMMAND_NAME))
async def vector_search_handler(message: Message, command: CommandObject) -> None:
    """Run vector search in-chat for development and QA checks."""

    if message.from_user is None:
        return

    query = extract_query_text(command)
    if not query:
        await message.bot.send_message(
            chat_id=message.chat.id,
            text=VS_USAGE_TEXT,
            parse_mode=None,
        )
        return

    try:
        response = _create_retrieval_service().search(
            query=query,
            rewrite_query=False,
        )
        result_messages = format_search_messages(query, response)
    except Exception:
        logger.exception(LOG_EVENT_BOT_VS_SEARCH_FAILED)
        await message.bot.send_message(
            chat_id=message.chat.id,
            text=VS_ERROR_TEXT,
            parse_mode=None,
        )
        return

    for rendered_message in result_messages:
        for chunk in split_for_telegram(rendered_message):
            await message.bot.send_message(
                chat_id=message.chat.id,
                text=chunk,
                parse_mode=None,
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
    """Handle unknown text content with guidance."""

    if message.from_user is None:
        return

    await messenger.send(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=UNKNOWN_TEXT_RESPONSE,
        reply_markup=build_main_menu_keyboard(),
    )
