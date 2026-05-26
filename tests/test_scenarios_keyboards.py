from __future__ import annotations

from app.bot.scenarios.callbacks import NAV_ACTION_BACK, NAV_ACTION_OPEN, ScenarioNavCallback
from app.bot.scenarios.catalog import (
    BACK_BUTTON_TEXT,
    BIRTHDAYS_NODE_ID,
    CAMPING_MAY_NODE_ID,
    CAMPING_NODE_ID,
    CAMPING_SUMMER_NODE_ID,
    CONTACTS_NODE_ID,
    DIRECTIONS_NODE_ID,
    ECOCAMP_NODE_ID,
    FAMILY_REST_NODE_ID,
    FAMILY_REST_PRICE_MAY_NODE_ID,
    FAMILY_REST_PRICE_NODE_ID,
    FAMILY_REST_PRICE_SUMMER_SATURDAY_NODE_ID,
    FAMILY_REST_PRICE_SUMMER_SUNDAY_NODE_ID,
    GAZEBOS_NODE_ID,
    GAZEBOS_TERMS_NODE_ID,
    MAIN_MENU_BACK_TARGET,
    MAIN_MENU_CONTACTS_TEXT,
    MAIN_MENU_DIRECTIONS_TEXT,
    OTHER_NODE_ID,
    OUTBOUND_WORKSHOPS_NODE_ID,
    PARK_SCHEDULE_MAY_NODE_ID,
    PARK_SCHEDULE_NODE_ID,
    PARK_SCHEDULE_SUMMER_NODE_ID,
    TRANSFER_DNIPRO_NODE_ID,
    TRANSFER_DNIPRO_TERMS_NODE_ID,
    TRANSFER_NODE_ID,
    TRANSFER_SAMAR_NODE_ID,
    TRANSFER_SAMAR_TERMS_NODE_ID,
    get_node,
)
from app.bot.scenarios.keyboards import (
    MAIN_MENU_BUTTON_TEXT,
    SECTION_MENU_BUTTON_TEXT,
    build_main_menu_keyboard,
    build_scenario_keyboard,
)


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


def test_family_rest_keyboard_has_expected_items_and_back_button() -> None:
    node = get_node(FAMILY_REST_NODE_ID)
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
        PARK_SCHEDULE_NODE_ID,
        FAMILY_REST_PRICE_NODE_ID,
        "camping",
        "gazebos",
        "transfer",
        DIRECTIONS_NODE_ID,
    ]


def test_park_schedule_keyboard_has_month_items_and_back_button() -> None:
    node = get_node(PARK_SCHEDULE_NODE_ID)
    assert node is not None
    assert node.text == "Оберіть місяць відвідування"

    keyboard = build_scenario_keyboard(node)
    assert keyboard is not None

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    callback_targets = [
        ScenarioNavCallback.unpack(button.callback_data).node_id
        for button in buttons
        if button.callback_data is not None
    ]
    assert callback_targets == [
        PARK_SCHEDULE_MAY_NODE_ID,
        PARK_SCHEDULE_SUMMER_NODE_ID,
        FAMILY_REST_NODE_ID,
    ]


def test_park_schedule_month_nodes_have_presenter_photos() -> None:
    may_node = get_node(PARK_SCHEDULE_MAY_NODE_ID)
    summer_node = get_node(PARK_SCHEDULE_SUMMER_NODE_ID)
    assert may_node is not None
    assert summer_node is not None

    assert len(may_node.photo_paths) == 1
    assert len(summer_node.photo_paths) == 2
    assert all(path.is_file() for path in may_node.photo_paths + summer_node.photo_paths)


def test_family_rest_price_keyboard_has_expected_items_and_back_button() -> None:
    node = get_node(FAMILY_REST_PRICE_NODE_ID)
    assert node is not None
    assert node.text == "Оберіть місяць та день відвідування"

    keyboard = build_scenario_keyboard(node)
    assert keyboard is not None

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    callback_targets = [
        ScenarioNavCallback.unpack(button.callback_data).node_id
        for button in buttons
        if button.callback_data is not None
    ]
    assert callback_targets == [
        FAMILY_REST_PRICE_MAY_NODE_ID,
        FAMILY_REST_PRICE_SUMMER_SATURDAY_NODE_ID,
        FAMILY_REST_PRICE_SUMMER_SUNDAY_NODE_ID,
        FAMILY_REST_NODE_ID,
    ]


def test_family_rest_price_nodes_have_presenter_photos() -> None:
    may_node = get_node(FAMILY_REST_PRICE_MAY_NODE_ID)
    saturday_node = get_node(FAMILY_REST_PRICE_SUMMER_SATURDAY_NODE_ID)
    sunday_node = get_node(FAMILY_REST_PRICE_SUMMER_SUNDAY_NODE_ID)
    assert may_node is not None
    assert saturday_node is not None
    assert sunday_node is not None

    assert len(may_node.photo_paths) == 1
    assert len(saturday_node.photo_paths) == 2
    assert len(sunday_node.photo_paths) == 2
    assert all(
        path.is_file()
        for path in may_node.photo_paths + saturday_node.photo_paths + sunday_node.photo_paths
    )


def test_camping_keyboard_has_month_items_and_back_button() -> None:
    node = get_node(CAMPING_NODE_ID)
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
        CAMPING_MAY_NODE_ID,
        CAMPING_SUMMER_NODE_ID,
        FAMILY_REST_NODE_ID,
    ]


def test_camping_month_nodes_render_section_navigation_keyboard() -> None:
    may_node = get_node(CAMPING_MAY_NODE_ID)
    summer_node = get_node(CAMPING_SUMMER_NODE_ID)
    assert may_node is not None
    assert summer_node is not None
    assert may_node.text.startswith("💰 Вартість перебування (травень):")
    assert summer_node.text

    for node in (may_node, summer_node):
        keyboard = build_scenario_keyboard(node)
        assert keyboard is not None

        buttons = [button for row in keyboard.inline_keyboard for button in row]
        assert [button.text for button in buttons] == [
            BACK_BUTTON_TEXT,
            SECTION_MENU_BUTTON_TEXT,
            MAIN_MENU_BUTTON_TEXT,
        ]
        callback_targets = [
            ScenarioNavCallback.unpack(button.callback_data).node_id
            for button in buttons
            if button.callback_data is not None
        ]
        assert callback_targets == [
            CAMPING_NODE_ID,
            FAMILY_REST_NODE_ID,
            DIRECTIONS_NODE_ID,
        ]


def test_gazebos_keyboard_has_terms_button_and_back_button() -> None:
    node = get_node(GAZEBOS_NODE_ID)
    assert node is not None
    assert len(node.photo_paths) == 1
    assert node.photo_paths[0].is_file()

    keyboard = build_scenario_keyboard(node)
    assert keyboard is not None

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    callback_targets = [
        ScenarioNavCallback.unpack(button.callback_data).node_id
        for button in buttons
        if button.callback_data is not None
    ]
    assert [button.text for button in buttons] == [
        "Умови відпочинку",
        BACK_BUTTON_TEXT,
    ]
    assert callback_targets == [
        GAZEBOS_TERMS_NODE_ID,
        FAMILY_REST_NODE_ID,
    ]


def test_gazebos_terms_node_renders_album_navigation_keyboard() -> None:
    node = get_node(GAZEBOS_TERMS_NODE_ID)
    assert node is not None
    assert len(node.photo_paths) == 2
    assert all(path.is_file() for path in node.photo_paths)

    keyboard = build_scenario_keyboard(node)
    assert keyboard is not None

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert [button.text for button in buttons] == [
        BACK_BUTTON_TEXT,
        SECTION_MENU_BUTTON_TEXT,
        MAIN_MENU_BUTTON_TEXT,
    ]
    callback_targets = [
        ScenarioNavCallback.unpack(button.callback_data).node_id
        for button in buttons
        if button.callback_data is not None
    ]
    assert callback_targets == [
        GAZEBOS_NODE_ID,
        FAMILY_REST_NODE_ID,
        DIRECTIONS_NODE_ID,
    ]


def test_transfer_keyboard_has_city_items_and_back_button() -> None:
    node = get_node(TRANSFER_NODE_ID)
    assert node is not None
    assert node.text == "Оберіть місто, з якого бажаєте до нас завітати"

    keyboard = build_scenario_keyboard(node)
    assert keyboard is not None

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert [button.text for button in buttons] == [
        "Дніпро",
        "Самар",
        BACK_BUTTON_TEXT,
    ]
    callback_targets = [
        ScenarioNavCallback.unpack(button.callback_data).node_id
        for button in buttons
        if button.callback_data is not None
    ]
    assert callback_targets == [
        TRANSFER_DNIPRO_NODE_ID,
        TRANSFER_SAMAR_NODE_ID,
        FAMILY_REST_NODE_ID,
    ]


def test_transfer_city_nodes_have_booking_actions() -> None:
    for node_id, terms_node_id in (
        (TRANSFER_DNIPRO_NODE_ID, TRANSFER_DNIPRO_TERMS_NODE_ID),
        (TRANSFER_SAMAR_NODE_ID, TRANSFER_SAMAR_TERMS_NODE_ID),
    ):
        node = get_node(node_id)
        assert node is not None
        assert "безкоштовний!🔥" in node.text

        keyboard = build_scenario_keyboard(node)
        assert keyboard is not None

        buttons = [button for row in keyboard.inline_keyboard for button in row]
        assert [button.text for button in buttons] == [
            "Умови бронювання",
            "Забронювати",
            BACK_BUTTON_TEXT,
        ]
        assert buttons[1].url == "https://berryland.com.ua/ts-1"
        assert ScenarioNavCallback.unpack(buttons[0].callback_data).node_id == terms_node_id
        assert ScenarioNavCallback.unpack(buttons[2].callback_data).node_id == TRANSFER_NODE_ID


def test_transfer_booking_terms_render_section_navigation_keyboard() -> None:
    for node_id, city_node_id in (
        (TRANSFER_DNIPRO_TERMS_NODE_ID, TRANSFER_DNIPRO_NODE_ID),
        (TRANSFER_SAMAR_TERMS_NODE_ID, TRANSFER_SAMAR_NODE_ID),
    ):
        node = get_node(node_id)
        assert node is not None
        assert node.text.startswith("Умови бронювання трансферу:")

        keyboard = build_scenario_keyboard(node)
        assert keyboard is not None

        buttons = [button for row in keyboard.inline_keyboard for button in row]
        assert [button.text for button in buttons] == [
            BACK_BUTTON_TEXT,
            SECTION_MENU_BUTTON_TEXT,
            MAIN_MENU_BUTTON_TEXT,
        ]
        callback_targets = [
            ScenarioNavCallback.unpack(button.callback_data).node_id
            for button in buttons
            if button.callback_data is not None
        ]
        assert callback_targets == [
            city_node_id,
            FAMILY_REST_NODE_ID,
            DIRECTIONS_NODE_ID,
        ]


def test_album_node_renders_navigation_keyboard() -> None:
    node = get_node(PARK_SCHEDULE_SUMMER_NODE_ID)
    assert node is not None

    keyboard = build_scenario_keyboard(node)
    assert keyboard is not None

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert [button.text for button in buttons] == [
        BACK_BUTTON_TEXT,
        SECTION_MENU_BUTTON_TEXT,
        MAIN_MENU_BUTTON_TEXT,
    ]
    callback_targets = [
        ScenarioNavCallback.unpack(button.callback_data).node_id
        for button in buttons
        if button.callback_data is not None
    ]
    assert callback_targets == [
        PARK_SCHEDULE_NODE_ID,
        FAMILY_REST_NODE_ID,
        DIRECTIONS_NODE_ID,
    ]


def test_text_leaf_node_renders_section_navigation_keyboard() -> None:
    leaf_node = get_node(BIRTHDAYS_NODE_ID)
    assert leaf_node is not None

    keyboard = build_scenario_keyboard(leaf_node)
    assert keyboard is not None

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert [button.text for button in buttons] == [
        BACK_BUTTON_TEXT,
        SECTION_MENU_BUTTON_TEXT,
        MAIN_MENU_BUTTON_TEXT,
    ]

    back_callback = buttons[0].callback_data
    assert back_callback is not None
    assert ScenarioNavCallback.unpack(back_callback).action == NAV_ACTION_BACK

    callback_targets = [
        ScenarioNavCallback.unpack(button.callback_data).node_id
        for button in buttons
        if button.callback_data is not None
    ]
    assert callback_targets == [
        OTHER_NODE_ID,
        OTHER_NODE_ID,
        DIRECTIONS_NODE_ID,
    ]


def test_child_buttons_use_open_callback_action() -> None:
    node = get_node(OTHER_NODE_ID)
    assert node is not None

    keyboard = build_scenario_keyboard(node)
    assert keyboard is not None

    first_callback = keyboard.inline_keyboard[0][0].callback_data
    assert first_callback is not None
    assert ScenarioNavCallback.unpack(first_callback).action == NAV_ACTION_OPEN
