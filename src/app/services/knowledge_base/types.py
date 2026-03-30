from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SplitMode = Literal["single", "column"]


@dataclass(slots=True)
class FileOverride:
    title: str | None = None
    category: str | None = None
    logical_id: str | None = None
    split_mode: SplitMode | None = None
    split_column_name: str | None = None
    section_column_name: str | None = None
    question_column_name: str | None = None
    answer_column_name: str | None = None


@dataclass(slots=True)
class ParseConfig:
    version: str = "1.0"
    logical_id_overrides: dict[str, str] = field(default_factory=dict)
    files: dict[str, FileOverride] = field(default_factory=dict)


@dataclass(slots=True)
class ManifestEntry:
    source_csv: str
    output_md_file: list[str]
    logical_id: str
    category: str
    version: str
    updated_at_utc: str
    row_count: int
    non_empty_cell_count: int
    content_hash_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source_csv": self.source_csv,
            "output_md_file": self.output_md_file,
            "logical_id": self.logical_id,
            "category": self.category,
            "version": self.version,
            "updated_at_utc": self.updated_at_utc,
            "row_count": self.row_count,
            "non_empty_cell_count": self.non_empty_cell_count,
            "content_hash_sha256": self.content_hash_sha256,
        }


@dataclass(slots=True)
class FileParseStats:
    source_csv: str
    parse_mode: str
    markdown_file_count: int
    row_count: int
    non_empty_cell_count: int


@dataclass(slots=True)
class FileParseError:
    source_csv: str
    error_type: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_csv": self.source_csv,
            "error_type": self.error_type,
            "message": self.message,
        }


@dataclass(slots=True)
class BatchParseResult:
    entries: list[ManifestEntry]
    errors: list[FileParseError]
    stats: list[FileParseStats]
    discovered_file_count: int
    manifest_path: Path

    @property
    def success_count(self) -> int:
        return len(self.entries)

    @property
    def failure_count(self) -> int:
        return len(self.errors)

    @property
    def all_files_failed(self) -> bool:
        return self.discovered_file_count == 0 or self.success_count == 0

