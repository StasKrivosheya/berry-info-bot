from __future__ import annotations

from app.bot.resources.keys import LinkKey, TextKey
from app.bot.resources.scenario_texts import LINKS, TEXTS, validate_resource_coverage


def test_text_keys_match_declared_enum() -> None:
    assert set(TEXTS) == set(TextKey)


def test_link_keys_match_declared_enum() -> None:
    assert set(LINKS) == set(LinkKey)


def test_resource_coverage_validation_passes() -> None:
    validate_resource_coverage()
