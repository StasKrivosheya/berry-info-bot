from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from app.services.knowledge_base.types_openai import ManifestSyncItem


@dataclass(slots=True)
class SyncPlan:
    selected_items: list[ManifestSyncItem]
    grouped_items: OrderedDict[str, list[ManifestSyncItem]]
    scanned_count: int
    selected_count: int
    skipped_count: int


def build_sync_plan(
    *,
    items: list[ManifestSyncItem],
    only_logical_id: str | None,
    only_category: str | None,
) -> SyncPlan:
    """Build deterministic sync plan with filters and logical_id grouping."""

    selected_items = [
        item
        for item in items
        if (only_logical_id is None or item.logical_id == only_logical_id)
        and (only_category is None or item.category == only_category)
    ]
    grouped_items: OrderedDict[str, list[ManifestSyncItem]] = OrderedDict()
    for item in sorted(
        selected_items,
        key=lambda value: (value.logical_id, value.markdown_relative_path.casefold()),
    ):
        grouped_items.setdefault(item.logical_id, []).append(item)

    scanned_count = len(items)
    selected_count = len(selected_items)
    skipped_count = scanned_count - selected_count
    return SyncPlan(
        selected_items=selected_items,
        grouped_items=grouped_items,
        scanned_count=scanned_count,
        selected_count=selected_count,
        skipped_count=skipped_count,
    )

