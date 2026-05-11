from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.scenarios.callbacks import NAV_ACTION_BACK, NAV_ACTION_OPEN, ScenarioNavCallback
from app.bot.scenarios.catalog import (
    BACK_BUTTON_TEXT,
    MAIN_MENU_BACK_TARGET,
    MAIN_MENU_CONTACTS_TEXT,
    MAIN_MENU_DIRECTIONS_TEXT,
)
from app.bot.scenarios.models import ScenarioNode

MAIN_MENU_BUTTON_TEXT = "Головне Меню"
SECTION_MENU_BUTTON_TEXT = "Меню Розділу"


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

    if len(node.photo_paths) > 1 and node.section_node_id is not None:
        return _build_album_navigation_keyboard(node)

    if not node.buttons and node.parent_node_id is None:
        return None

    builder = InlineKeyboardBuilder()
    for button in node.buttons:
        if button.target_node_id is not None:
            _add_nav_button(
                builder,
                text=button.text,
                action=NAV_ACTION_OPEN,
                node_id=button.target_node_id,
            )
        else:
            builder.button(text=button.text, url=button.url)

    if node.parent_node_id is not None:
        _add_nav_button(
            builder,
            text=BACK_BUTTON_TEXT,
            action=NAV_ACTION_BACK,
            node_id=node.parent_node_id,
        )

    builder.adjust(1)
    return builder.as_markup()


def _build_album_navigation_keyboard(node: ScenarioNode) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if node.parent_node_id is not None:
        _add_nav_button(
            builder,
            text=BACK_BUTTON_TEXT,
            action=NAV_ACTION_BACK,
            node_id=node.parent_node_id,
        )

    _add_nav_button(
        builder,
        text=SECTION_MENU_BUTTON_TEXT,
        action=NAV_ACTION_OPEN,
        node_id=node.section_node_id,
    )
    _add_nav_button(
        builder,
        text=MAIN_MENU_BUTTON_TEXT,
        action=NAV_ACTION_BACK,
        node_id=MAIN_MENU_BACK_TARGET,
    )

    builder.adjust(1)
    return builder.as_markup()


def _add_nav_button(
    builder: InlineKeyboardBuilder,
    *,
    text: str,
    action: str,
    node_id: str,
) -> None:
    callback_data = ScenarioNavCallback(action=action, node_id=node_id).pack()
    builder.button(text=text, callback_data=callback_data)
