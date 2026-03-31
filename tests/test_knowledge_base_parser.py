from __future__ import annotations

import json
from pathlib import Path

from app.services.knowledge_base.cli import main
from app.services.knowledge_base.parser import parse_knowledge_base


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_multiline_cells_render_and_manifest_is_generated(tmp_path: Path) -> None:
    input_dir = tmp_path / "raw"
    output_dir = tmp_path / "processed"
    config_path = tmp_path / "parser_config.toml"

    _write_text(
        input_dir / "faq.csv",
        'Question,Answer\n"How to order?","Step one.\n\nStep two."\n',
    )
    _write_text(
        config_path,
        """
[files."faq.csv"]
question_column_name = "Question"
answer_column_name = "Answer"
""".strip(),
    )

    result = parse_knowledge_base(
        input_dir=input_dir,
        output_dir=output_dir,
        config_path=config_path,
    )

    assert result.success_count == 1
    assert result.failure_count == 0
    markdown_path = output_dir / "markdown" / "faq.md"
    manifest_path = output_dir / "manifest.json"
    assert markdown_path.exists()
    assert manifest_path.exists()

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# Faq" in markdown
    assert "### How to order?" in markdown
    assert "Step one.\n\nStep two." in markdown

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "generated_at_utc" in manifest
    assert manifest["entries"][0]["source_csv"] == "faq.csv"
    assert manifest["entries"][0]["output_md_file"] == ["markdown/faq.md"]
    assert manifest["entries"][0]["content_hash_sha256"]


def test_manifest_hash_and_logical_id_are_stable_across_runs(tmp_path: Path) -> None:
    input_dir = tmp_path / "raw"
    output_dir = tmp_path / "processed"
    config_path = tmp_path / "parser_config.toml"

    _write_text(input_dir / "01-faq.csv", "Question,Answer\nQ1,A1\n")
    _write_text(
        config_path,
        """
[logical_id_overrides]
"01-faq" = "mapped-id"

[files."01-faq.csv"]
logical_id = "file-level-id"
question_column_name = "Question"
answer_column_name = "Answer"
""".strip(),
    )

    first = parse_knowledge_base(
        input_dir=input_dir,
        output_dir=output_dir,
        config_path=config_path,
    )
    second = parse_knowledge_base(
        input_dir=input_dir,
        output_dir=output_dir,
        config_path=config_path,
    )

    assert first.entries[0].logical_id == "file-level-id"
    assert second.entries[0].logical_id == "file-level-id"
    assert first.entries[0].output_md_file == ["markdown/01-faq.md"]
    assert second.entries[0].output_md_file == ["markdown/01-faq.md"]
    assert first.entries[0].content_hash_sha256 == second.entries[0].content_hash_sha256


def test_partial_failure_does_not_fail_batch_but_all_fail_returns_non_zero(tmp_path: Path) -> None:
    input_dir = tmp_path / "raw"
    output_dir = tmp_path / "processed"
    config_path = tmp_path / "parser_config.toml"

    _write_text(input_dir / "ok.csv", "Header,Value\nTopic,Text\n")
    # Missing closing quote triggers csv.Error in strict mode.
    _write_text(input_dir / "broken.csv", 'Question,Answer\n"Broken,Cell\n')
    _write_text(config_path, "")

    result = parse_knowledge_base(
        input_dir=input_dir,
        output_dir=output_dir,
        config_path=config_path,
    )
    assert result.success_count == 1
    assert result.failure_count == 1
    assert not result.all_files_failed

    exit_code_partial = main(
        [
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--config",
            str(config_path),
        ]
    )
    assert exit_code_partial == 0

    only_broken_input = tmp_path / "raw_only_broken"
    only_broken_output = tmp_path / "processed_only_broken"
    _write_text(only_broken_input / "broken.csv", 'Question,Answer\n"Broken,Cell\n')
    exit_code_all_failed = main(
        [
            "--input-dir",
            str(only_broken_input),
            "--output-dir",
            str(only_broken_output),
            "--config",
            str(config_path),
        ]
    )
    assert exit_code_all_failed == 1


def test_parser_rerun_keeps_markdown_bytes_and_stable_manifest_entry_fields(tmp_path: Path) -> None:
    input_dir = tmp_path / "raw"
    output_dir = tmp_path / "processed"
    config_path = tmp_path / "parser_config.toml"

    _write_text(input_dir / "faq.csv", "Question,Answer\nQ1,A1\nQ2,A2\n")
    _write_text(
        config_path,
        """
[files."faq.csv"]
question_column_name = "Question"
answer_column_name = "Answer"
""".strip(),
    )

    parse_knowledge_base(input_dir=input_dir, output_dir=output_dir, config_path=config_path)
    first_markdown = (output_dir / "markdown" / "faq.md").read_bytes()
    first_manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    first_entry = first_manifest["entries"][0]

    parse_knowledge_base(input_dir=input_dir, output_dir=output_dir, config_path=config_path)
    second_markdown = (output_dir / "markdown" / "faq.md").read_bytes()
    second_manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    second_entry = second_manifest["entries"][0]

    assert first_markdown == second_markdown
    assert first_entry["source_csv"] == second_entry["source_csv"]
    assert first_entry["output_md_file"] == second_entry["output_md_file"]
    assert first_entry["logical_id"] == second_entry["logical_id"]
    assert first_entry["category"] == second_entry["category"]
    assert first_entry["version"] == second_entry["version"]
    assert first_entry["row_count"] == second_entry["row_count"]
    assert first_entry["non_empty_cell_count"] == second_entry["non_empty_cell_count"]
    assert first_entry["content_hash_sha256"] == second_entry["content_hash_sha256"]
