from __future__ import annotations

from app.services.knowledge_base.normalizer import (
    legacy_ascii_slugify,
    normalize_cell_text,
    slugify,
)


def test_normalize_cell_text_preserves_paragraph_breaks() -> None:
    raw = "  First   line \r\n\r\n  Second\tline\r\n\r\n\r\nThird   line  "
    normalized = normalize_cell_text(raw)
    assert normalized == "First line\n\nSecond line\n\nThird line"


def test_slugify_is_deterministic_for_mixed_input() -> None:
    value = " Uber Cafe -- HELP__Desk! "
    expected = "uber-cafe-help-desk"
    assert slugify(value) == expected
    assert slugify(value) == expected


def test_slugify_transliterates_cyrillic_input() -> None:
    assert slugify("Інформаційні повідомлення 26") == "informatsiini-povidomlennia-26"


def test_slugify_has_unicode_fallback_for_non_cyrillic_scripts() -> None:
    assert slugify("東京 ラーメン") == "東京-ラーメン"


def test_legacy_ascii_slugify_preserves_previous_ascii_stripping_behavior() -> None:
    assert legacy_ascii_slugify("Інформаційні повідомлення 26") == "26"
