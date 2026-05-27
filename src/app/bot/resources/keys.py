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
