from __future__ import annotations

from app.services.knowledge_base.normalizer import normalize_cell_text, slugify


def test_normalize_cell_text_preserves_paragraph_breaks() -> None:
    raw = "  First   line \r\n\r\n  Second\tline\r\n\r\n\r\nThird   line  "
    normalized = normalize_cell_text(raw)
    assert normalized == "First line\n\nSecond line\n\nThird line"


def test_slugify_is_deterministic_for_mixed_input() -> None:
    value = " Über Café -- HELP__Desk! "
    expected = "uber-cafe-help-desk"
    assert slugify(value) == expected
    assert slugify(value) == expected


def test_slugify_has_unicode_fallback() -> None:
    assert slugify("Привіт світ") == "привіт-світ"

