from __future__ import annotations

from app.bot.resources.keys import TextKey
from app.bot.resources.scenario_texts import get_text
from app.bot.scenarios.catalog import (
    BACK_BUTTON_TEXT,
    CONTACTS_NODE_ID,
    DIRECTIONS_NODE_ID,
    FAMILY_REST_NODE_ID,
    MAIN_MENU_CONTACTS_TEXT,
    MAIN_MENU_DIRECTIONS_TEXT,
    get_node,
)
from app.bot.scenarios.keyboards import build_main_menu_keyboard, build_scenario_keyboard


def test_main_menu_keyboard_has_two_entry_buttons() -> None:
    keyboard = build_main_menu_keyboard()
    labels = [button.text for row in keyboard.keyboard for button in row]
    assert labels == [MAIN_MENU_DIRECTIONS_TEXT, MAIN_MENU_CONTACTS_TEXT]


def test_directions_keyboard_has_expected_items_and_back_button() -> None:
    node = get_node(DIRECTIONS_NODE_ID)
    assert node is not None

    keyboard = build_scenario_keyboard(node)
    assert keyboard is not None

    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert labels == [
        get_text(TextKey.BUTTON_FAMILY_REST),
        get_text(TextKey.BUTTON_CHILD_PROGRAM),
        get_text(TextKey.BUTTON_OUTBOUND_WORKSHOPS),
        BACK_BUTTON_TEXT,
    ]


def test_contacts_keyboard_has_links_and_back_button() -> None:
    node = get_node(CONTACTS_NODE_ID)
    assert node is not None

    keyboard = build_scenario_keyboard(node)
    assert keyboard is not None

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    labels = [button.text for button in buttons]
    assert labels == [
        get_text(TextKey.BUTTON_INSTAGRAM),
        get_text(TextKey.BUTTON_GOOGLE_MAPS),
        BACK_BUTTON_TEXT,
    ]
    assert buttons[0].url is not None
    assert buttons[1].url is not None


def test_leaf_node_renders_only_back_button() -> None:
    node = get_node(FAMILY_REST_NODE_ID)
    assert node is not None

    first_child_callback = node.buttons[0].target_node_id
    assert first_child_callback is not None

    leaf_node = get_node(first_child_callback)
    assert leaf_node is not None

    keyboard = build_scenario_keyboard(leaf_node)
    assert keyboard is not None

    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert labels == [BACK_BUTTON_TEXT]
