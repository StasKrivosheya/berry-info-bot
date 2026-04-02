from __future__ import annotations

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

router = Router(name="scenarios")
messenger = ScenarioMessenger()


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
