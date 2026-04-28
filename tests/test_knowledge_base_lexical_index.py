from __future__ import annotations

import json
from pathlib import Path

from app.services.knowledge_base.cli import main as kb_rebuild_main
from app.services.knowledge_base.retrieval.candidates import build_candidates_from_manifest
from app.services.knowledge_base.retrieval.lexical import (
    SQLiteLexicalIndex,
    build_lexical_index_from_manifest,
)


def write_tiny_manifest(tmp_path: Path) -> Path:
    output_dir = tmp_path / "processed"
    markdown_dir = output_dir / "markdown"
    markdown_dir.mkdir(parents=True)
    (markdown_dir / "programs.md").write_text(
        "\n".join(
            (
                "# Організовані програми",
                "",
                "## Програма пригод",
                "Квест, поні-ферма та активності для дітей.",
                "",
                "## Трансфер",
                "Трансфер з Дніпра оплачується окремо.",
            )
        ),
        encoding="utf-8",
    )
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "output_dir": output_dir.as_posix(),
                "entries": [
                    {
                        "source_file": "kb.xlsx",
                        "source_format": "xlsx",
                        "sheet_name": "Programs",
                        "sheet_index": 1,
                        "workbook_file": "kb.xlsx",
                        "output_md_file": ["markdown/programs.md"],
                        "logical_id": "programs",
                        "category": "programs",
                        "direction_id": "op",
                        "topic_ids": ["programs", "transfer"],
                        "period_label": "test period",
                        "version": "1.0",
                        "updated_at_utc": "2026-04-27T00:00:00+00:00",
                        "row_count": 5,
                        "non_empty_cell_count": 5,
                        "content_hash_sha256": "hash-programs",
                    }
                ],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_build_candidates_from_manifest_contains_stable_metadata(tmp_path: Path) -> None:
    manifest_path = write_tiny_manifest(tmp_path)

    candidates = build_candidates_from_manifest(manifest_path)

    assert len(candidates) == 2
    first = candidates[0]
    assert first.candidate_id == first.section_id
    assert first.logical_id == "programs"
    assert first.category == "programs"
    assert first.direction_id == "op"
    assert "programs" in first.topic_ids
    assert first.period_label == "test period"
    assert first.source_file == "kb.xlsx"
    assert first.sheet_name == "Programs"
    assert first.sheet_index == 1
    assert first.workbook_file == "kb.xlsx"
    assert first.heading_path[:1] == ("Організовані програми",)
    assert first.content


def test_sqlite_lexical_index_builds_and_searches_keywords_and_phrases(tmp_path: Path) -> None:
    manifest_path = write_tiny_manifest(tmp_path)
    index_path = tmp_path / "kb.sqlite3"

    report = build_lexical_index_from_manifest(manifest_path, index_path=index_path)
    hits = SQLiteLexicalIndex(index_path).search(
        keywords=("поні-ферма",),
        phrases=("активності для дітей",),
        max_results=5,
    )

    assert report.index_path == index_path.resolve()
    assert report.candidate_count == 2
    assert len(hits) == 1
    assert hits[0].candidate.logical_id == "programs"
    assert "Програма пригод" in hits[0].candidate.heading_path
    assert "поні-ферма" in hits[0].candidate.content
    assert hits[0].score >= 0


def test_sqlite_lexical_index_returns_empty_for_no_results(tmp_path: Path) -> None:
    manifest_path = write_tiny_manifest(tmp_path)
    index_path = tmp_path / "kb.sqlite3"
    build_lexical_index_from_manifest(manifest_path, index_path=index_path)

    hits = SQLiteLexicalIndex(index_path).search(keywords=("аквапарк",), max_results=5)

    assert hits == ()


def test_kb_rebuild_cli_builds_lexical_index(tmp_path: Path) -> None:
    input_dir = tmp_path / "raw"
    output_dir = tmp_path / "processed"
    config_path = tmp_path / "parser_config.toml"
    index_path = tmp_path / "custom.sqlite3"
    input_dir.mkdir()
    (input_dir / "faq.csv").write_text(
        "Question,Answer\n"
        '"Які є програми?","Berry Land має організовані програми для дітей."\n',
        encoding="utf-8",
    )
    config_path.write_text(
        """
[files."faq.csv"]
question_column_name = "Question"
answer_column_name = "Answer"
""".strip(),
        encoding="utf-8",
    )

    exit_code = kb_rebuild_main(
        [
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--config",
            str(config_path),
            "--lexical-index",
            str(index_path),
        ]
    )
    hits = SQLiteLexicalIndex(index_path).search(keywords=("організовані програми",))

    assert exit_code == 0
    assert (output_dir / "manifest.json").exists()
    assert index_path.exists()
    assert len(hits) == 1
