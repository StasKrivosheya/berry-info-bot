from __future__ import annotations

from enum import StrEnum


class TextKey(StrEnum):
    """Keys for localized text resources."""

    MENU_DIRECTIONS = "menu.directions"
    MENU_CONTACTS = "menu.contacts"
    MENU_BACK = "menu.back"
    MENU_MAIN_MESSAGE = "menu.main_message"

    KEYWORD_2026_VALUE = "keyword.2026.value"
    KEYWORD_2026_RESPONSE = "keyword.2026.response"

    FALLBACK_UNKNOWN_TEXT = "fallback.unknown_text"
    FALLBACK_UNKNOWN_MESSAGE_TYPE = "fallback.unknown_message_type"
    FALLBACK_MISSING_NODE = "fallback.missing_node"

    BUTTON_FAMILY_REST = "button.family_rest"
    BUTTON_CHILD_PROGRAM = "button.child_program"
    BUTTON_OUTBOUND_WORKSHOPS = "button.outbound_workshops"
    BUTTON_PARK_SCHEDULE = "button.park_schedule"
    BUTTON_DATES = "button.dates"
    BUTTON_CAMPING = "button.camping"
    BUTTON_GAZEBOS = "button.gazebos"
    BUTTON_TRANSFER = "button.transfer"
    BUTTON_INSTAGRAM = "button.instagram"
    BUTTON_GOOGLE_MAPS = "button.google_maps"

    NODE_DIRECTIONS_TEXT = "node.directions.text"
    NODE_FAMILY_REST_TEXT = "node.family_rest.text"
    NODE_CHILD_PROGRAM_TEXT = "node.child_program.text"
    NODE_OUTBOUND_WORKSHOPS_TEXT = "node.outbound_workshops.text"
    NODE_PARK_SCHEDULE_TEXT = "node.park_schedule.text"
    NODE_DATES_TEXT = "node.dates.text"
    NODE_CAMPING_TEXT = "node.camping.text"
    NODE_GAZEBOS_TEXT = "node.gazebos.text"
    NODE_TRANSFER_TEXT = "node.transfer.text"
    NODE_CONTACTS_TEXT = "node.contacts.text"


class LinkKey(StrEnum):
    """Keys for external URL resources."""

    INSTAGRAM = "link.instagram"
    GOOGLE_MAPS = "link.google_maps"
