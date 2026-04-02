from __future__ import annotations

from pathlib import Path

import pytest

from app.services.knowledge_base.ingest.parser import parse_knowledge_base

REAL_WORKBOOK_PATH = Path("data/knowledge_base/raw_sources") / (
    "\u0406\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0456\u0439\u043d\u0456 "
    "\u043f\u043e\u0432\u0456\u0434\u043e\u043c\u043b\u0435\u043d\u043d\u044f 26.xlsx"
)
PARSER_CONFIG_PATH = Path("data/knowledge_base/parser_config.toml")
EXPECTED_FIRST_FIVE_SHEETS = [
    "\u041e\u041f \u0432\u0435\u0441\u043d\u0430-\u043b\u0456\u0442\u043e",
    "\u041e\u043f\u0438\u0441 \u043f\u0440\u043e\u0433\u0440\u0430\u043c",
    (
        "\u0421\u0412 "
        "(\u041a\u0412\u0406\u0422\u0415\u041d\u042c-\u0422\u0420\u0410\u0412\u0415\u041d\u042c)"
    ),
    "\u041a\u0435\u043c\u043f\u0456\u043d\u0433",
    "\u0422\u0440\u0430\u043d\u0441\u0444\u0435\u0440",
]


@pytest.mark.skipif(not REAL_WORKBOOK_PATH.exists(), reason="Local workbook is not available.")
def test_local_real_workbook_first_five_sheets_parse_stably(tmp_path: Path) -> None:
    first = parse_knowledge_base(
        input_dir=REAL_WORKBOOK_PATH.parent,
        output_dir=tmp_path / "first",
        config_path=PARSER_CONFIG_PATH,
    )
    second = parse_knowledge_base(
        input_dir=REAL_WORKBOOK_PATH.parent,
        output_dir=tmp_path / "second",
        config_path=PARSER_CONFIG_PATH,
    )

    assert first.failure_count == 0
    assert second.failure_count == 0
    assert [entry.source_file for entry in first.entries] == [REAL_WORKBOOK_PATH.name] * 5
    assert [entry.source_format for entry in first.entries] == ["xlsx"] * 5
    assert [entry.sheet_name for entry in first.entries] == EXPECTED_FIRST_FIVE_SHEETS
    assert [entry.sheet_name for entry in second.entries] == EXPECTED_FIRST_FIVE_SHEETS
    assert [entry.content_hash_sha256 for entry in first.entries] == [
        entry.content_hash_sha256 for entry in second.entries
    ]

