from __future__ import annotations

from collections.abc import Mapping

from app.bot.resources.keys import LinkKey, TextKey
from app.bot.resources.scenario_texts import get_link, get_text
from app.bot.scenarios.models import ScenarioButton, ScenarioNode

MAIN_MENU_BACK_TARGET = "__main_menu__"

# Shared UI labels and responses reused across multiple modules.
MAIN_MENU_DIRECTIONS_TEXT = get_text(TextKey.MENU_DIRECTIONS)
MAIN_MENU_CONTACTS_TEXT = get_text(TextKey.MENU_CONTACTS)
BACK_BUTTON_TEXT = get_text(TextKey.MENU_BACK)
MENU_MESSAGE_TEXT = get_text(TextKey.MENU_MAIN_MESSAGE)
KEYWORD_2026_TEXT = get_text(TextKey.KEYWORD_2026_VALUE)
KEYWORD_2026_RESPONSE = get_text(TextKey.KEYWORD_2026_RESPONSE)
UNKNOWN_TEXT_RESPONSE = get_text(TextKey.FALLBACK_UNKNOWN_TEXT)
UNKNOWN_MESSAGE_TYPE_RESPONSE = get_text(TextKey.FALLBACK_UNKNOWN_MESSAGE_TYPE)
MISSING_NODE_RESPONSE = get_text(TextKey.FALLBACK_MISSING_NODE)

# Scenario graph node identifiers.
DIRECTIONS_NODE_ID = "directions"
CONTACTS_NODE_ID = "contacts"
FAMILY_REST_NODE_ID = "family_rest"
CHILD_PROGRAM_NODE_ID = "child_program"
OUTBOUND_WORKSHOPS_NODE_ID = "outbound_workshops"
PARK_SCHEDULE_NODE_ID = "park_schedule"
DATES_NODE_ID = "dates"
CAMPING_NODE_ID = "camping"
GAZEBOS_NODE_ID = "gazebos"
TRANSFER_NODE_ID = "transfer"

SCENARIO_NODES: Mapping[str, ScenarioNode] = {
    DIRECTIONS_NODE_ID: ScenarioNode(
        node_id=DIRECTIONS_NODE_ID,
        text=get_text(TextKey.NODE_DIRECTIONS_TEXT),
        parent_node_id=MAIN_MENU_BACK_TARGET,
        buttons=(
            ScenarioButton(
                text=get_text(TextKey.BUTTON_FAMILY_REST),
                target_node_id=FAMILY_REST_NODE_ID,
            ),
            ScenarioButton(
                text=get_text(TextKey.BUTTON_CHILD_PROGRAM),
                target_node_id=CHILD_PROGRAM_NODE_ID,
            ),
            ScenarioButton(
                text=get_text(TextKey.BUTTON_OUTBOUND_WORKSHOPS),
                target_node_id=OUTBOUND_WORKSHOPS_NODE_ID,
            ),
        ),
    ),
    CONTACTS_NODE_ID: ScenarioNode(
        node_id=CONTACTS_NODE_ID,
        text=get_text(TextKey.NODE_CONTACTS_TEXT),
        parent_node_id=MAIN_MENU_BACK_TARGET,
        buttons=(
            ScenarioButton(
                text=get_text(TextKey.BUTTON_INSTAGRAM),
                url=get_link(LinkKey.INSTAGRAM),
            ),
            ScenarioButton(
                text=get_text(TextKey.BUTTON_GOOGLE_MAPS),
                url=get_link(LinkKey.GOOGLE_MAPS),
            ),
        ),
    ),
    FAMILY_REST_NODE_ID: ScenarioNode(
        node_id=FAMILY_REST_NODE_ID,
        text=get_text(TextKey.NODE_FAMILY_REST_TEXT),
        parent_node_id=DIRECTIONS_NODE_ID,
        buttons=(
            ScenarioButton(
                text=get_text(TextKey.BUTTON_PARK_SCHEDULE),
                target_node_id=PARK_SCHEDULE_NODE_ID,
            ),
            ScenarioButton(
                text=get_text(TextKey.BUTTON_DATES),
                target_node_id=DATES_NODE_ID,
            ),
            ScenarioButton(
                text=get_text(TextKey.BUTTON_CAMPING),
                target_node_id=CAMPING_NODE_ID,
            ),
            ScenarioButton(
                text=get_text(TextKey.BUTTON_GAZEBOS),
                target_node_id=GAZEBOS_NODE_ID,
            ),
            ScenarioButton(
                text=get_text(TextKey.BUTTON_TRANSFER),
                target_node_id=TRANSFER_NODE_ID,
            ),
        ),
    ),
    CHILD_PROGRAM_NODE_ID: ScenarioNode(
        node_id=CHILD_PROGRAM_NODE_ID,
        text=get_text(TextKey.NODE_CHILD_PROGRAM_TEXT),
        parent_node_id=DIRECTIONS_NODE_ID,
    ),
    OUTBOUND_WORKSHOPS_NODE_ID: ScenarioNode(
        node_id=OUTBOUND_WORKSHOPS_NODE_ID,
        text=get_text(TextKey.NODE_OUTBOUND_WORKSHOPS_TEXT),
        parent_node_id=DIRECTIONS_NODE_ID,
    ),
    PARK_SCHEDULE_NODE_ID: ScenarioNode(
        node_id=PARK_SCHEDULE_NODE_ID,
        text=get_text(TextKey.NODE_PARK_SCHEDULE_TEXT),
        parent_node_id=FAMILY_REST_NODE_ID,
    ),
    DATES_NODE_ID: ScenarioNode(
        node_id=DATES_NODE_ID,
        text=get_text(TextKey.NODE_DATES_TEXT),
        parent_node_id=FAMILY_REST_NODE_ID,
    ),
    CAMPING_NODE_ID: ScenarioNode(
        node_id=CAMPING_NODE_ID,
        text=get_text(TextKey.NODE_CAMPING_TEXT),
        parent_node_id=FAMILY_REST_NODE_ID,
    ),
    GAZEBOS_NODE_ID: ScenarioNode(
        node_id=GAZEBOS_NODE_ID,
        text=get_text(TextKey.NODE_GAZEBOS_TEXT),
        parent_node_id=FAMILY_REST_NODE_ID,
    ),
    TRANSFER_NODE_ID: ScenarioNode(
        node_id=TRANSFER_NODE_ID,
        text=get_text(TextKey.NODE_TRANSFER_TEXT),
        parent_node_id=FAMILY_REST_NODE_ID,
    ),
}

MAIN_MENU_ACTIONS: Mapping[str, str] = {
    MAIN_MENU_DIRECTIONS_TEXT: DIRECTIONS_NODE_ID,
    MAIN_MENU_CONTACTS_TEXT: CONTACTS_NODE_ID,
}


def get_node(node_id: str) -> ScenarioNode | None:
    """Return scenario node by id or None when not configured."""

    return SCENARIO_NODES.get(node_id)
