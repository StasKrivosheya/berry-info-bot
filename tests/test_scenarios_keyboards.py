from __future__ import annotations

from app.bot.scenarios.callbacks import NAV_ACTION_BACK, NAV_ACTION_OPEN, ScenarioNavCallback
from app.bot.scenarios.catalog import (
    BACK_BUTTON_TEXT,
    BIRTHDAYS_NODE_ID,
    CONTACTS_NODE_ID,
    DIRECTIONS_NODE_ID,
    ECOCAMP_NODE_ID,
    FAMILY_REST_NODE_ID,
    MAIN_MENU_BACK_TARGET,
    MAIN_MENU_CONTACTS_TEXT,
    MAIN_MENU_DIRECTIONS_TEXT,
    OTHER_NODE_ID,
    OUTBOUND_WORKSHOPS_NODE_ID,
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

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    callback_targets = [
        ScenarioNavCallback.unpack(button.callback_data).node_id
        for button in buttons
        if button.callback_data is not None
    ]
    assert callback_targets == [
        "family_rest",
        "organized_programs",
        ECOCAMP_NODE_ID,
        "other",
        MAIN_MENU_BACK_TARGET,
    ]
    assert buttons[-1].text == BACK_BUTTON_TEXT


def test_contacts_keyboard_has_links_and_back_button() -> None:
    node = get_node(CONTACTS_NODE_ID)
    assert node is not None

    keyboard = build_scenario_keyboard(node)
    assert keyboard is not None

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert [button.url for button in buttons[:3]] == [
        "https://www.instagram.com/berryland_dnipro/",
        "https://maps.app.goo.gl/jhKpvRc2m93Nj2BF7",
        "https://berryland.com.ua",
    ]
    assert buttons[-1].text == BACK_BUTTON_TEXT


def test_other_keyboard_has_expected_items_and_back_button() -> None:
    node = get_node(OTHER_NODE_ID)
    assert node is not None

    keyboard = build_scenario_keyboard(node)
    assert keyboard is not None

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    callback_targets = [
        ScenarioNavCallback.unpack(button.callback_data).node_id
        for button in buttons
        if button.callback_data is not None
    ]
    assert callback_targets == [
        OUTBOUND_WORKSHOPS_NODE_ID,
        BIRTHDAYS_NODE_ID,
        DIRECTIONS_NODE_ID,
    ]


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

    back_callback = keyboard.inline_keyboard[0][0].callback_data
    assert back_callback is not None
    assert ScenarioNavCallback.unpack(back_callback).action == NAV_ACTION_BACK


def test_child_buttons_use_open_callback_action() -> None:
    node = get_node(OTHER_NODE_ID)
    assert node is not None

    keyboard = build_scenario_keyboard(node)
    assert keyboard is not None

    first_callback = keyboard.inline_keyboard[0][0].callback_data
    assert first_callback is not None
    assert ScenarioNavCallback.unpack(first_callback).action == NAV_ACTION_OPEN
