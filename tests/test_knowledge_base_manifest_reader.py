from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.knowledge_base.manifest_reader import load_manifest_sync_items


def test_load_manifest_sync_items_raises_on_incomplete_entries(tmp_path: Path) -> None:
    manifest_path = tmp_path / "processed" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "output_dir": ".",
                "entries": [
                    {
                        "source_file": "faq.csv",
                        "source_format": "csv",
                        "sheet_name": None,
                        "workbook_file": None,
                        "output_md_file": ["markdown/faq.md"],
                        "logical_id": "",
                        "category": "faq",
                        "version": "1.0",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-empty 'logical_id'"):
        load_manifest_sync_items(manifest_path)


def test_load_manifest_sync_items_uses_manifest_directory_for_invalid_relative_output_dir(
    tmp_path: Path,
) -> None:
    manifest_dir = tmp_path / "job" / "processed"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "output_dir": "some/other/path",
                "entries": [
                    {
                        "source_file": "faq.csv",
                        "source_format": "csv",
                        "sheet_name": None,
                        "workbook_file": None,
                        "output_md_file": ["markdown/faq.md"],
                        "logical_id": "faq",
                        "category": "faq",
                        "version": "1.0",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    items = load_manifest_sync_items(manifest_path)

    assert items[0].markdown_absolute_path == (manifest_dir / "markdown" / "faq.md").resolve()


def test_load_manifest_sync_items_accepts_legacy_source_csv_field(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "processed"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "output_dir": ".",
                "entries": [
                    {
                        "source_csv": "faq.csv",
                        "output_md_file": ["markdown/faq.md"],
                        "logical_id": "faq",
                        "category": "faq",
                        "version": "1.0",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    items = load_manifest_sync_items(manifest_path)

    assert items[0].source_file == "faq.csv"
    assert items[0].source_format == "csv"
    assert items[0].sheet_name is None
    assert items[0].workbook_file is None
