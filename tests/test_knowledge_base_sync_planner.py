from __future__ import annotations

from pathlib import Path

from app.services.knowledge_base.sync_planner import build_sync_plan
from app.services.knowledge_base.types_openai import ManifestSyncItem


def _item(
    *,
    logical_id: str,
    category: str,
    markdown_relative_path: str,
) -> ManifestSyncItem:
    return ManifestSyncItem(
        logical_id=logical_id,
        category=category,
        version="1.0",
        updated_at_utc="2026-03-30T00:00:00+00:00",
        source_file=f"{logical_id}.csv",
        source_format="csv",
        sheet_name=None,
        sheet_index=None,
        workbook_file=None,
        content_hash_sha256="hash",
        markdown_relative_path=markdown_relative_path,
        markdown_absolute_path=Path(f"/tmp/{markdown_relative_path}"),
    )


def test_build_sync_plan_groups_items_by_logical_id_in_deterministic_order() -> None:
    items = [
        _item(logical_id="faq", category="general", markdown_relative_path="markdown/faq--b.md"),
        _item(logical_id="faq", category="general", markdown_relative_path="markdown/faq--a.md"),
        _item(logical_id="shipping", category="ops", markdown_relative_path="markdown/ship.md"),
    ]

    plan = build_sync_plan(items=items, only_logical_id=None, only_category=None)

    assert plan.scanned_count == 3
    assert plan.selected_count == 3
    assert plan.skipped_count == 0
    assert list(plan.grouped_items.keys()) == ["faq", "shipping"]
    assert [item.markdown_relative_path for item in plan.grouped_items["faq"]] == [
        "markdown/faq--a.md",
        "markdown/faq--b.md",
    ]


def test_build_sync_plan_applies_logical_id_and_category_filters() -> None:
    items = [
        _item(logical_id="faq", category="general", markdown_relative_path="markdown/faq.md"),
        _item(
            logical_id="support",
            category="general",
            markdown_relative_path="markdown/support.md",
        ),
        _item(logical_id="ops", category="internal", markdown_relative_path="markdown/ops.md"),
    ]

    by_id = build_sync_plan(items=items, only_logical_id="support", only_category=None)
    assert by_id.selected_count == 1
    assert by_id.skipped_count == 2
    assert list(by_id.grouped_items.keys()) == ["support"]

    by_category = build_sync_plan(items=items, only_logical_id=None, only_category="general")
    assert by_category.selected_count == 2
    assert by_category.skipped_count == 1
    assert list(by_category.grouped_items.keys()) == ["faq", "support"]
