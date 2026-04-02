from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from app.services.knowledge_base.normalizer import normalize_cell_text

SUPPORTED_ENCODINGS = ("utf-8-sig", "cp1251")


@dataclass(slots=True)
class PreparedTable:
    rows: list[list[str]]
    row_count: int
    non_empty_cell_count: int


def read_and_prepare_csv(csv_path: Path) -> PreparedTable:
    """Read CSV file and return normalized table with empty rows/cols removed."""

    csv_bytes = csv_path.read_bytes()
    csv_text = decode_csv_bytes(csv_bytes)

    reader = csv.reader(io.StringIO(csv_text, newline=""), strict=True)
    normalized_rows = [[normalize_cell_text(cell) for cell in row] for row in reader]
    non_empty_rows = [row for row in normalized_rows if any(cell for cell in row)]
    trimmed_rows = trim_empty_columns(non_empty_rows)

    row_count = len(trimmed_rows)
    non_empty_cell_count = sum(1 for row in trimmed_rows for cell in row if cell)
    return PreparedTable(
        rows=trimmed_rows,
        row_count=row_count,
        non_empty_cell_count=non_empty_cell_count,
    )


def decode_csv_bytes(csv_bytes: bytes) -> str:
    decode_error: UnicodeDecodeError | None = None
    for encoding in SUPPORTED_ENCODINGS:
        try:
            return csv_bytes.decode(encoding)
        except UnicodeDecodeError as exc:
            decode_error = exc
    if decode_error is None:
        msg = "Failed to decode CSV bytes with configured encodings."
        raise ValueError(msg)
    raise decode_error


def trim_empty_columns(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return []

    max_columns = max(len(row) for row in rows)
    padded_rows = [row + [""] * (max_columns - len(row)) for row in rows]
    non_empty_indexes = [
        index for index in range(max_columns) if any(row[index] for row in padded_rows)
    ]
    return [[row[index] for index in non_empty_indexes] for row in padded_rows]

