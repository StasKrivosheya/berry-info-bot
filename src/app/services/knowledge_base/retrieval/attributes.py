from __future__ import annotations

from typing import Any

from app.services.knowledge_base.types_openai import Attributes


def normalize_attributes(raw_attributes: object) -> Attributes:
    """Normalize arbitrary SDK attributes payload into supported primitive map."""

    if not isinstance(raw_attributes, dict):
        return {}

    normalized: Attributes = {}
    for key, value in raw_attributes.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, (str, int, float, bool)):
            normalized[key] = value
    return normalized


def build_filters_payload(filters: Attributes) -> dict[str, Any] | None:
    """Build deterministic OpenAI vector-search filter payload."""

    if not filters:
        return None

    filter_items = [
        {
            "type": "eq",
            "key": key,
            "value": value,
        }
        for key, value in sorted(filters.items(), key=lambda item: item[0])
    ]
    if len(filter_items) == 1:
        return filter_items[0]

    return {
        "type": "and",
        "filters": filter_items,
    }


def build_search_attributes(
    *,
    attribute_filters: Attributes | None,
    category: str | None,
    logical_id: str | None,
    language: str = "uk",
) -> Attributes:
    """Merge search attributes with deterministic language default."""

    merged: Attributes = {"language": language}
    if attribute_filters:
        merged.update(attribute_filters)
    if category is not None:
        merged["category"] = category
    if logical_id is not None:
        merged["logical_id"] = logical_id
    return merged

