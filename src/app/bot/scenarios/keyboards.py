from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.scenarios.callbacks import NAV_ACTION_BACK, NAV_ACTION_OPEN, ScenarioNavCallback
from app.bot.scenarios.catalog import (
    BACK_BUTTON_TEXT,
    MAIN_MENU_CONTACTS_TEXT,
    MAIN_MENU_DIRECTIONS_TEXT,
)
from app.bot.scenarios.models import ScenarioNode


def build_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Return persistent top-level keyboard with entry points."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=MAIN_MENU_DIRECTIONS_TEXT),
                KeyboardButton(text=MAIN_MENU_CONTACTS_TEXT),
            ],
        ],
        resize_keyboard=True,
    )


def build_scenario_keyboard(node: ScenarioNode) -> InlineKeyboardMarkup | None:
    """Build inline keyboard from scenario node configuration."""

    if not node.buttons and node.parent_node_id is None:
        return None

    builder = InlineKeyboardBuilder()
    for button in node.buttons:
        if button.target_node_id is not None:
            callback_data = ScenarioNavCallback(
                action=NAV_ACTION_OPEN,
                node_id=button.target_node_id,
            ).pack()
            builder.button(text=button.text, callback_data=callback_data)
        else:
            builder.button(text=button.text, url=button.url)

    if node.parent_node_id is not None:
        callback_data = ScenarioNavCallback(
            action=NAV_ACTION_BACK,
            node_id=node.parent_node_id,
        ).pack()
        builder.button(text=BACK_BUTTON_TEXT, callback_data=callback_data)

    builder.adjust(1)
    return builder.as_markup()
