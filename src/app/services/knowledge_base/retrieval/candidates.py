from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.services.knowledge_base.manifest.reader import load_manifest_sync_items
from app.services.knowledge_base.query.structure import KnowledgeBaseStructureReader
from app.services.knowledge_base.query.types import StructuredDocument, StructuredSection
from app.services.knowledge_base.taxonomy import get_default_taxonomy
from app.services.knowledge_base.types_openai import ManifestSyncItem


@dataclass(frozen=True, slots=True)
class KnowledgeBaseCandidate:
    candidate_id: str
    logical_id: str
    section_id: str
    category: str
    source_category: str
    direction_id: str | None
    topic_ids: tuple[str, ...]
    period_label: str | None
    heading_path: tuple[str, ...]
    content: str
    source_file: str
    source_format: str
    sheet_name: str | None
    sheet_index: int | None
    workbook_file: str | None
    markdown_path: str


def build_candidates_from_manifest(manifest_path: Path) -> tuple[KnowledgeBaseCandidate, ...]:
    """Build stable section-level candidates from processed manifest markdown."""

    manifest_path = manifest_path.resolve()
    items = load_manifest_sync_items(manifest_path)
    items_by_path = {item.markdown_absolute_path.resolve(): item for item in items}
    documents = KnowledgeBaseStructureReader(manifest_path).load_documents()

    candidates: list[KnowledgeBaseCandidate] = []
    for document in documents:
        item = items_by_path.get(document.markdown_path.resolve())
        if item is None:
            continue
        candidates.extend(_document_candidates(document, item))

    candidates.sort(key=lambda candidate: candidate.candidate_id)
    return tuple(candidates)


def stable_section_id(logical_id: str, heading_path: tuple[str, ...]) -> str:
    """Return a stable content identity shared by vector and lexical normalization."""

    normalized_path = "\n".join(part.strip().casefold() for part in heading_path if part.strip())
    if not normalized_path:
        normalized_path = logical_id.strip().casefold()
    digest = hashlib.sha1(normalized_path.encode("utf-8")).hexdigest()[:16]
    return f"{logical_id}:{digest}"


def _document_candidates(
    document: StructuredDocument,
    item: ManifestSyncItem,
) -> list[KnowledgeBaseCandidate]:
    if not document.sections:
        markdown = document.markdown_path.read_text(encoding="utf-8")
        heading_path = (document.title,) if document.title else (document.logical_id,)
        return [
            _candidate_from_parts(
                document=document,
                item=item,
                heading_path=heading_path,
                content=markdown,
            )
        ]

    candidates: list[KnowledgeBaseCandidate] = []
    for section in document.sections:
        candidates.append(_candidate_from_section(document=document, item=item, section=section))
    return candidates


def _candidate_from_section(
    *,
    document: StructuredDocument,
    item: ManifestSyncItem,
    section: StructuredSection,
) -> KnowledgeBaseCandidate:
    content_parts = [*section.heading_path, section.body]
    content = "\n".join(part for part in content_parts if part)
    return _candidate_from_parts(
        document=document,
        item=item,
        heading_path=section.heading_path or (section.heading,),
        content=content,
    )


def _candidate_from_parts(
    *,
    document: StructuredDocument,
    item: ManifestSyncItem,
    heading_path: tuple[str, ...],
    content: str,
) -> KnowledgeBaseCandidate:
    section_id = stable_section_id(document.logical_id, heading_path)
    taxonomy = get_default_taxonomy()
    section_topic_ids = (
        taxonomy.infer_topic_ids_from_text("\n".join((*heading_path, content)))
        or item.topic_ids
    )
    return KnowledgeBaseCandidate(
        candidate_id=section_id,
        logical_id=document.logical_id,
        section_id=section_id,
        category=document.category,
        source_category=document.category,
        direction_id=item.direction_id,
        topic_ids=section_topic_ids,
        period_label=item.period_label,
        heading_path=heading_path,
        content=content.strip(),
        source_file=item.source_file,
        source_format=item.source_format,
        sheet_name=item.sheet_name,
        sheet_index=item.sheet_index,
        workbook_file=item.workbook_file,
        markdown_path=item.markdown_relative_path,
    )
