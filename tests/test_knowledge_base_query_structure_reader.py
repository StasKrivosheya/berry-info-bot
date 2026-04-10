from __future__ import annotations

import json
from pathlib import Path

from app.services.knowledge_base.query.structure import KnowledgeBaseStructureReader


def test_structure_reader_reload_documents_when_manifest_changes(tmp_path: Path) -> None:
    processed_dir = tmp_path / "processed"
    markdown_dir = processed_dir / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = markdown_dir / "catalog.md"
    markdown_path.write_text("# Version A\n\n## Section\n\nText A\n", encoding="utf-8")

    manifest_path = processed_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "output_dir": processed_dir.as_posix(),
                "entries": [
                    {
                        "source_file": "catalog.xlsx",
                        "source_format": "xlsx",
                        "sheet_name": "Catalog",
                        "sheet_index": 1,
                        "workbook_file": "catalog.xlsx",
                        "output_md_file": ["markdown/catalog.md"],
                        "logical_id": "catalog",
                        "category": "catalog",
                        "version": "1.0",
                        "updated_at_utc": "2026-04-08T00:00:00+00:00",
                        "content_hash_sha256": "hash-a",
                    }
                ],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )

    reader = KnowledgeBaseStructureReader(manifest_path)
    first = reader.load_documents()
    assert len(first) == 1
    assert first[0].title == "Version A"

    markdown_path.write_text("# Version B\n\n## Section\n\nText B\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "output_dir": processed_dir.as_posix(),
                "entries": [
                    {
                        "source_file": "catalog.xlsx",
                        "source_format": "xlsx",
                        "sheet_name": "Catalog",
                        "sheet_index": 1,
                        "workbook_file": "catalog.xlsx",
                        "output_md_file": ["markdown/catalog.md"],
                        "logical_id": "catalog",
                        "category": "catalog",
                        "version": "1.0",
                        "updated_at_utc": "2026-04-08T00:01:00+00:00",
                        "content_hash_sha256": "hash-b",
                    }
                ],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )

    second = reader.load_documents()
    assert len(second) == 1
    assert second[0].title == "Version B"
