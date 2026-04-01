from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ParserProfile = Literal["qa_table", "section_table", "column_split", "outline_sheet"]
SourceFormat = Literal["csv", "xlsx", "unknown"]
SelectableSourceFormat = Literal["csv", "xlsx"]


@dataclass(slots=True)
class ParseDiagnostic:
    code: str
    message: str
    row_numbers: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "row_numbers": list(self.row_numbers),
        }


@dataclass(slots=True)
class SourceOverride:
    parser_profile: ParserProfile | None = None
    title: str | None = None
    category: str | None = None
    logical_id: str | None = None
    split_column_name: str | None = None
    section_column_name: str | None = None
    question_column_name: str | None = None
    answer_column_name: str | None = None
    content_ranges: tuple[str, ...] = ()
    ignore_rows: tuple[int, ...] = ()
    ignore_columns: tuple[str, ...] = ()
    forced_header_rows: tuple[int, ...] = ()
    forced_paragraph_rows: tuple[int, ...] = ()
    ignore: bool = False

    def merged_with(self, override: SourceOverride | None) -> SourceOverride:
        if override is None:
            return SourceOverride(
                parser_profile=self.parser_profile,
                title=self.title,
                category=self.category,
                logical_id=self.logical_id,
                split_column_name=self.split_column_name,
                section_column_name=self.section_column_name,
                question_column_name=self.question_column_name,
                answer_column_name=self.answer_column_name,
                content_ranges=self.content_ranges,
                ignore_rows=self.ignore_rows,
                ignore_columns=self.ignore_columns,
                forced_header_rows=self.forced_header_rows,
                forced_paragraph_rows=self.forced_paragraph_rows,
                ignore=self.ignore,
            )

        return SourceOverride(
            parser_profile=override.parser_profile or self.parser_profile,
            title=override.title or self.title,
            category=override.category or self.category,
            logical_id=override.logical_id or self.logical_id,
            split_column_name=override.split_column_name or self.split_column_name,
            section_column_name=override.section_column_name or self.section_column_name,
            question_column_name=override.question_column_name or self.question_column_name,
            answer_column_name=override.answer_column_name or self.answer_column_name,
            content_ranges=override.content_ranges or self.content_ranges,
            ignore_rows=override.ignore_rows or self.ignore_rows,
            ignore_columns=override.ignore_columns or self.ignore_columns,
            forced_header_rows=override.forced_header_rows or self.forced_header_rows,
            forced_paragraph_rows=override.forced_paragraph_rows or self.forced_paragraph_rows,
            ignore=override.ignore or self.ignore,
        )


@dataclass(slots=True)
class FileOverride(SourceOverride):
    sheet_indexes: tuple[int, ...] = ()
    sheets: dict[str, SourceOverride] = field(default_factory=dict)


@dataclass(slots=True)
class ParseConfig:
    version: str = "1.0"
    source_formats: tuple[SelectableSourceFormat, ...] = ("csv", "xlsx")
    logical_id_overrides: dict[str, str] = field(default_factory=dict)
    files: dict[str, FileOverride] = field(default_factory=dict)


@dataclass(slots=True)
class ManifestEntry:
    source_file: str
    source_format: SourceFormat
    sheet_name: str | None
    sheet_index: int | None
    workbook_file: str | None
    output_md_file: list[str]
    logical_id: str
    category: str
    version: str
    updated_at_utc: str
    row_count: int
    non_empty_cell_count: int
    content_hash_sha256: str
    diagnostics: list[ParseDiagnostic] = field(default_factory=list)

    @property
    def source_ref(self) -> str:
        if self.sheet_name:
            return f"{self.source_file}#{self.sheet_name}"
        return self.source_file

    def to_dict(self) -> dict[str, object]:
        return {
            "source_file": self.source_file,
            "source_format": self.source_format,
            "sheet_name": self.sheet_name,
            "sheet_index": self.sheet_index,
            "workbook_file": self.workbook_file,
            "output_md_file": self.output_md_file,
            "logical_id": self.logical_id,
            "category": self.category,
            "version": self.version,
            "updated_at_utc": self.updated_at_utc,
            "row_count": self.row_count,
            "non_empty_cell_count": self.non_empty_cell_count,
            "content_hash_sha256": self.content_hash_sha256,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


@dataclass(slots=True)
class FileParseStats:
    source_file: str
    source_format: SourceFormat
    sheet_name: str | None
    sheet_index: int | None
    workbook_file: str | None
    parse_mode: str
    markdown_file_count: int
    row_count: int
    non_empty_cell_count: int

    @property
    def source_ref(self) -> str:
        if self.sheet_name:
            return f"{self.source_file}#{self.sheet_name}"
        return self.source_file


@dataclass(slots=True)
class FileParseError:
    source_file: str
    source_format: SourceFormat
    sheet_name: str | None
    sheet_index: int | None
    workbook_file: str | None
    error_type: str
    message: str
    diagnostics: list[ParseDiagnostic] = field(default_factory=list)

    @property
    def source_ref(self) -> str:
        if self.sheet_name:
            return f"{self.source_file}#{self.sheet_name}"
        return self.source_file

    def to_dict(self) -> dict[str, object]:
        return {
            "source_file": self.source_file,
            "source_format": self.source_format,
            "sheet_name": self.sheet_name,
            "sheet_index": self.sheet_index,
            "workbook_file": self.workbook_file,
            "error_type": self.error_type,
            "message": self.message,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


@dataclass(slots=True)
class BatchParseResult:
    entries: list[ManifestEntry]
    errors: list[FileParseError]
    stats: list[FileParseStats]
    discovered_source_count: int
    manifest_path: Path

    @property
    def success_count(self) -> int:
        return len(self.entries)

    @property
    def failure_count(self) -> int:
        return len(self.errors)

    @property
    def all_files_failed(self) -> bool:
        return self.discovered_source_count == 0 or self.success_count == 0

    @property
    def discovered_file_count(self) -> int:
        """Backward-compatible alias for earlier result naming."""

        return self.discovered_source_count
