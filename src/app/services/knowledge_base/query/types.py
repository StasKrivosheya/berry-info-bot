from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StructuredSection:
    heading: str
    level: int
    heading_path: tuple[str, ...]
    body: str


@dataclass(frozen=True, slots=True)
class StructuredDocument:
    logical_id: str
    title: str
    category: str
    source_file: str
    markdown_path: Path
    scopes: tuple[str, ...]
    sections: tuple[StructuredSection, ...]


@dataclass(frozen=True, slots=True)
class SearchHitDebugContext:
    logical_id: str
    source_file: str | None
    document_title: str | None
    heading_path: tuple[str, ...] = field(default_factory=tuple)
