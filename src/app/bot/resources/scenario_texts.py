from __future__ import annotations

from collections.abc import Mapping

from app.bot.resources.keys import TextKey

# ruff: noqa: RUF001

TEXTS: Mapping[TextKey, str] = {
    TextKey.MENU_DIRECTIONS: "Направлення",
    TextKey.MENU_CONTACTS: "Контакти",
    TextKey.MENU_BACK: "Назад",
    TextKey.MENU_MAIN_MESSAGE: "Оберіть розділ нижче.",
    TextKey.KEYWORD_2026_VALUE: "2026",
    TextKey.KEYWORD_2026_RESPONSE: (
        "Актуальна інформація станом на 2026 рік."
    ),
    TextKey.FALLBACK_UNKNOWN_TEXT: (
        "Поки що не готовий дати відповідь на це. "
        "Скористайтесь кнопками меню або ключовим словом 2026."
    ),
    TextKey.FALLBACK_UNKNOWN_MESSAGE_TYPE: (
        "Поки що підтримуються лише текстові запити. "
        "Скористайтесь меню або словом 2026."
    ),
    TextKey.FALLBACK_MISSING_NODE: (
        "Розділ тимчасово недоступний. "
        "Спробуйте обрати інший пункт меню."
    ),
}


def get_text(key: TextKey) -> str:
    """Return localized text resource by key."""

    return TEXTS[key]


def validate_resource_coverage() -> None:
    """Ensure text map fully covers declared resource keys."""

    text_keys = set(TEXTS)
    expected_text_keys = set(TextKey)
    if text_keys != expected_text_keys:
        missing = expected_text_keys - text_keys
        unknown = text_keys - expected_text_keys
        msg = f"Text resources mismatch. Missing: {missing}. Unknown: {unknown}."
        raise ValueError(msg)

