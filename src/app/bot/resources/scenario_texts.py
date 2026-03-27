from __future__ import annotations

from collections.abc import Mapping

from app.bot.resources.keys import LinkKey, TextKey

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
    TextKey.BUTTON_FAMILY_REST: "Сімейний відпочинок",
    TextKey.BUTTON_CHILD_PROGRAM: "Програма дитячого відпочинку",
    TextKey.BUTTON_OUTBOUND_WORKSHOPS: "Виїзні майстеркласи",
    TextKey.BUTTON_PARK_SCHEDULE: "Графік роботи парку",
    TextKey.BUTTON_DATES: "Дати",
    TextKey.BUTTON_CAMPING: "Кемпінг",
    TextKey.BUTTON_GAZEBOS: "Альтанки",
    TextKey.BUTTON_TRANSFER: "Трансфер",
    TextKey.BUTTON_INSTAGRAM: "Instagram",
    TextKey.BUTTON_GOOGLE_MAPS: "Google Карти",
    TextKey.NODE_DIRECTIONS_TEXT: "Інформація про Направлення",
    TextKey.NODE_FAMILY_REST_TEXT: "Інформація про Сімейний відпочинок",
    TextKey.NODE_CHILD_PROGRAM_TEXT: "Інформація про Програма дитячого відпочинку",
    TextKey.NODE_OUTBOUND_WORKSHOPS_TEXT: "Інформація про Виїзні майстеркласи",
    TextKey.NODE_PARK_SCHEDULE_TEXT: "Інформація про Графік роботи парку",
    TextKey.NODE_DATES_TEXT: "Інформація про Дати",
    TextKey.NODE_CAMPING_TEXT: "Інформація про Кемпінг",
    TextKey.NODE_GAZEBOS_TEXT: "Інформація про Альтанки",
    TextKey.NODE_TRANSFER_TEXT: "Інформація про Трансфер",
    TextKey.NODE_CONTACTS_TEXT: (
        "Години роботи: (тимчасово зачинено)\n"
        "Телефон: +380502770107\n"
        "Адреса парку: вул. Центральна, 1б, Євецько-Миколаївка, "
        "Дніпропетровська область, 51253"
    ),
}

LINKS: Mapping[LinkKey, str] = {
    LinkKey.INSTAGRAM: "https://www.instagram.com/berryland_dnipro/",
    LinkKey.GOOGLE_MAPS: "https://maps.app.goo.gl/jhKpvRc2m93Nj2BF7",
}


def get_text(key: TextKey) -> str:
    """Return localized text resource by key."""

    return TEXTS[key]


def get_link(key: LinkKey) -> str:
    """Return external URL resource by key."""

    return LINKS[key]


def validate_resource_coverage() -> None:
    """Ensure text/link maps fully cover declared resource keys."""

    text_keys = set(TEXTS)
    expected_text_keys = set(TextKey)
    if text_keys != expected_text_keys:
        missing = expected_text_keys - text_keys
        unknown = text_keys - expected_text_keys
        msg = f"Text resources mismatch. Missing: {missing}. Unknown: {unknown}."
        raise ValueError(msg)

    link_keys = set(LINKS)
    expected_link_keys = set(LinkKey)
    if link_keys != expected_link_keys:
        missing = expected_link_keys - link_keys
        unknown = link_keys - expected_link_keys
        msg = f"Link resources mismatch. Missing: {missing}. Unknown: {unknown}."
        raise ValueError(msg)
