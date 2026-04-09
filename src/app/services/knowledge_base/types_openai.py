from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

AttributeValue = str | int | float | bool
Attributes = dict[str, AttributeValue]
NO_RELEVANT_INFO_FALLBACK = "No relevant information found in the knowledge base."


@dataclass(slots=True)
class ManifestSyncItem:
    logical_id: str
    category: str
    version: str
    updated_at_utc: str
    source_file: str
    source_format: str
    sheet_name: str | None
    sheet_index: int | None
    workbook_file: str | None
    content_hash_sha256: str
    markdown_relative_path: str
    markdown_absolute_path: Path

    @property
    def upload_attributes(self) -> Attributes:
        attributes: Attributes = {
            "logical_id": self.logical_id,
            "category": self.category,
            "version": self.version,
            "updated_at_utc": self.updated_at_utc,
            "source_file": self.source_file,
            "source_format": self.source_format,
            "language": "uk",
            "content_hash_sha256": self.content_hash_sha256,
        }
        if self.sheet_name:
            attributes["sheet_name"] = self.sheet_name
        if self.sheet_index is not None:
            attributes["sheet_index"] = str(self.sheet_index)
        if self.workbook_file:
            attributes["workbook_file"] = self.workbook_file
        if self.source_format == "csv":
            attributes["source_csv"] = self.source_file
        return attributes


@dataclass(slots=True)
class VectorStoreFileRecord:
    file_id: str
    filename: str
    attributes: Attributes = field(default_factory=dict)


@dataclass(slots=True)
class DeleteReport:
    logical_id: str
    matched_count: int
    deleted_count: int
    deleted_underlying_count: int
    deleted_file_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DeleteRecordsReport:
    matched_count: int
    deleted_count: int
    deleted_underlying_count: int
    deleted_file_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UploadResult:
    file_id: str
    filename: str
    logical_id: str
    dry_run: bool = False


@dataclass(slots=True)
class SyncFailure:
    operation: str
    logical_id: str
    markdown_path: str | None
    error_type: str
    message: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "operation": self.operation,
            "logical_id": self.logical_id,
            "markdown_path": self.markdown_path,
            "error_type": self.error_type,
            "message": self.message,
        }


@dataclass(slots=True)
class SyncReport:
    manifest_path: Path
    dry_run: bool
    replace: bool
    scanned_count: int = 0
    selected_count: int = 0
    skipped_count: int = 0
    deleted_count: int = 0
    deleted_underlying_count: int = 0
    uploaded_count: int = 0
    failures: list[SyncFailure] = field(default_factory=list)

    @property
    def failed_count(self) -> int:
        return len(self.failures)

    @property
    def has_failures(self) -> bool:
        return self.failed_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_path": self.manifest_path.as_posix(),
            "dry_run": self.dry_run,
            "replace": self.replace,
            "scanned_count": self.scanned_count,
            "selected_count": self.selected_count,
            "skipped_count": self.skipped_count,
            "deleted_count": self.deleted_count,
            "deleted_underlying_count": self.deleted_underlying_count,
            "uploaded_count": self.uploaded_count,
            "failed_count": self.failed_count,
            "failures": [failure.to_dict() for failure in self.failures],
        }


@dataclass(slots=True)
class SearchHit:
    file_id: str
    filename: str
    score: float
    attributes: Attributes
    text: str


@dataclass(slots=True)
class SearchResponse:
    results: list[SearchHit]
    top_score: float | None
    used_threshold: float
    fallback_triggered: bool
    fallback_message: str | None = None
