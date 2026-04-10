from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from app.services.knowledge_base.types_openai import SearchHit


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    """Return values without duplicates while preserving first-seen order."""

    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def search_hit_logical_id(hit: SearchHit, *, use_filename_stem: bool = True) -> str:
    """Resolve logical_id from hit attributes with deterministic filename fallback."""

    logical_id = attribute_as_str(hit.attributes.get("logical_id"))
    if logical_id:
        return logical_id
    if use_filename_stem:
        return Path(hit.filename).stem
    return hit.filename


def attribute_as_str(value: object) -> str | None:
    """Normalize primitive attribute values into stable non-empty strings."""

    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:g}"
    normalized = str(value).strip()
    return normalized or None

