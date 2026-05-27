from __future__ import annotations

from collections.abc import Mapping

from app.bot.resources.keys import TextKey
from app.bot.resources.scenario_texts import get_text
from app.bot.scenarios.loader import DEFAULT_SCENARIO_CONFIG_PATH, load_scenario_catalog
from app.bot.scenarios.models import ScenarioNode

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
ORGANIZED_PROGRAMS_NODE_ID = "organized_programs"
ORGANIZED_PROGRAMS_DETAILS_NODE_ID = "organized_programs_details"
ORGANIZED_PROGRAMS_PRICE_NODE_ID = "organized_programs_price"
ORGANIZED_PROGRAMS_TOPICS_NODE_ID = "organized_programs_topics"
ORGANIZED_PROGRAMS_EXTRAS_NODE_ID = "organized_programs_extras"
ORGANIZED_PROGRAMS_BERRY_EXPEDITION_NODE_ID = "organized_programs_berry_expedition"
ORGANIZED_PROGRAMS_RANCH_ADVENTURES_NODE_ID = "organized_programs_ranch_adventures"
ORGANIZED_PROGRAMS_GRADUATION_LEVEL_NODE_ID = "organized_programs_graduation_level"
ORGANIZED_PROGRAMS_TEAM_VIBE_NODE_ID = "organized_programs_team_vibe"
ORGANIZED_PROGRAMS_BUBBLE_BOOM_NODE_ID = "organized_programs_bubble_boom"
ORGANIZED_PROGRAMS_OVERNIGHT_NODE_ID = "organized_programs_overnight"
ORGANIZED_PROGRAMS_PRESCHOOL_GRADUATION_NODE_ID = "organized_programs_preschool_graduation"
ECOCAMP_NODE_ID = "ecocamp"
ECOCAMP_PRICE_NODE_ID = "ecocamp_price"
ECOCAMP_SCHEDULE_NODE_ID = "ecocamp_schedule"
OTHER_NODE_ID = "other"
OUTBOUND_WORKSHOPS_NODE_ID = "outbound_workshops"
BIRTHDAYS_NODE_ID = "birthdays"
PARK_SCHEDULE_NODE_ID = "park_schedule"
PARK_SCHEDULE_MAY_NODE_ID = "park_schedule_may"
PARK_SCHEDULE_SUMMER_NODE_ID = "park_schedule_summer"
FAMILY_REST_PRICE_NODE_ID = "family_rest_price"
FAMILY_REST_PRICE_MAY_NODE_ID = "family_rest_price_may"
FAMILY_REST_PRICE_SUMMER_SATURDAY_NODE_ID = "family_rest_price_summer_saturday"
FAMILY_REST_PRICE_SUMMER_SUNDAY_NODE_ID = "family_rest_price_summer_sunday"
CAMPING_NODE_ID = "camping"
CAMPING_MAY_NODE_ID = "camping_may"
CAMPING_SUMMER_NODE_ID = "camping_summer"
GAZEBOS_NODE_ID = "gazebos"
GAZEBOS_TERMS_NODE_ID = "gazebos_terms"
TRANSFER_NODE_ID = "transfer"
TRANSFER_DNIPRO_NODE_ID = "transfer_dnipro"
TRANSFER_DNIPRO_TERMS_NODE_ID = "transfer_dnipro_terms"
TRANSFER_SAMAR_NODE_ID = "transfer_samar"
TRANSFER_SAMAR_TERMS_NODE_ID = "transfer_samar_terms"

_SCENARIO_CATALOG = load_scenario_catalog(
    DEFAULT_SCENARIO_CONFIG_PATH,
    main_menu_back_target=MAIN_MENU_BACK_TARGET,
)

SCENARIO_NODES: Mapping[str, ScenarioNode] = _SCENARIO_CATALOG.nodes
MAIN_MENU_ACTIONS: Mapping[str, str] = _SCENARIO_CATALOG.main_menu_actions


def get_node(node_id: str) -> ScenarioNode | None:
    """Return scenario node by id or None when not configured."""

    return SCENARIO_NODES.get(node_id)
