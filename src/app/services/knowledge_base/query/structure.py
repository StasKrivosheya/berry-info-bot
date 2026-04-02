from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

from app.services.knowledge_base.manifest.reader import load_manifest_sync_items
from app.services.knowledge_base.normalizer import normalize_cell_text
from app.services.knowledge_base.query.rules import SCOPE_RULES
from app.services.knowledge_base.query.text import token_overlap_score, tokenize_text
from app.services.knowledge_base.query.types import (
    QueryScopeName,
    SearchHitDebugContext,
    StructuredDocument,
    StructuredSection,
)
from app.services.knowledge_base.types_openai import SearchHit

logger = logging.getLogger(__name__)

DEFAULT_MANIFEST_PATH = Path("data/knowledge_base/processed/manifest.json")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
LOG_EVENT_STRUCTURE_LOADED = "kb_structure_loaded"


class KnowledgeBaseStructureReader:
    """Read processed KB structure from manifest + markdown files."""

    def __init__(self, manifest_path: Path | None = None) -> None:
        self._manifest_path = (manifest_path or DEFAULT_MANIFEST_PATH).resolve()

    @property
    def manifest_path(self) -> Path:
        return self._manifest_path

    def load_documents(self) -> tuple[StructuredDocument, ...]:
        return _load_documents_cached(self._manifest_path)

    def documents_for_scopes(
        self,
        scopes: tuple[QueryScopeName, ...],
    ) -> tuple[StructuredDocument, ...]:
        documents = self.load_documents()
        if not documents:
            return ()
        filtered = [
            document
            for document in documents
            if "general" in scopes or any(scope in document.scopes for scope in scopes)
        ]
        return tuple(filtered or documents)

    def resolve_hit_context(self, hit: SearchHit) -> SearchHitDebugContext | None:
        documents = self.load_documents()
        if not documents:
            return None

        logical_id = str(hit.attributes.get("logical_id", "")).strip() or Path(hit.filename).stem
        documents_by_id = {document.logical_id: document for document in documents}
        document = documents_by_id.get(logical_id)
        if document is None:
            return None

        section = _match_section(hit.text, document.sections)
        if section is None:
            return SearchHitDebugContext(
                logical_id=document.logical_id,
                source_file=document.source_file or None,
                document_title=document.title or None,
                heading_path=(document.title,) if document.title else (),
            )

        return SearchHitDebugContext(
            logical_id=document.logical_id,
            source_file=document.source_file or None,
            document_title=document.title or None,
            heading_path=section.heading_path,
        )


@lru_cache(maxsize=4)
def _load_documents_cached(manifest_path: Path) -> tuple[StructuredDocument, ...]:
    if not manifest_path.exists():
        return ()

    items = load_manifest_sync_items(manifest_path)
    documents: list[StructuredDocument] = []
    for item in items:
        markdown_path = item.markdown_absolute_path
        if not markdown_path.exists():
            continue
        markdown = markdown_path.read_text(encoding="utf-8")
        title, sections = _parse_outline(markdown)
        scopes = _infer_document_scopes(
            title=title,
            category=item.category,
            sections=tuple(sections),
        )
        documents.append(
            StructuredDocument(
                logical_id=item.logical_id,
                title=title or item.logical_id,
                category=item.category,
                source_file=item.source_file,
                markdown_path=markdown_path,
                scopes=scopes,
                sections=tuple(sections),
            )
        )

    documents.sort(
        key=lambda document: (
            document.logical_id,
            document.markdown_path.name.casefold(),
        )
    )
    logger.info(
        "%s manifest=%s document_count=%s",
        LOG_EVENT_STRUCTURE_LOADED,
        manifest_path.as_posix(),
        len(documents),
    )
    return tuple(documents)


def _parse_outline(markdown: str) -> tuple[str, list[StructuredSection]]:
    title = ""
    preamble_lines: list[str] = []
    sections: list[StructuredSection] = []
    heading_stack: list[str] = []
    current_heading = ""
    current_level = 0
    current_path: tuple[str, ...] = ()
    current_body: list[str] = []

    def flush_section() -> None:
        if not current_heading:
            return
        sections.append(
            StructuredSection(
                heading=current_heading,
                level=current_level,
                heading_path=current_path,
                body=normalize_cell_text("\n".join(current_body)),
            )
        )

    for raw_line in normalize_cell_text(markdown).splitlines():
        match = HEADING_RE.match(raw_line)
        if match is None:
            if current_heading:
                current_body.append(raw_line)
            else:
                preamble_lines.append(raw_line)
            continue

        flush_section()
        current_heading = ""
        current_level = 0
        current_path = ()
        current_body = []

        level = len(match.group(1))
        heading_text = normalize_cell_text(match.group(2))
        if level == 1 and not title:
            title = heading_text
            heading_stack = []
            continue

        while len(heading_stack) >= max(1, level - 1):
            heading_stack.pop()
        heading_stack.append(heading_text)

        current_heading = heading_text
        current_level = level
        current_path = (title, *heading_stack) if title else tuple(heading_stack)

    flush_section()

    preamble = normalize_cell_text("\n".join(preamble_lines))
    if preamble and title:
        sections.insert(
            0,
            StructuredSection(
                heading=title,
                level=1,
                heading_path=(title,),
                body=preamble,
            )
        )

    return title, sections


def _infer_document_scopes(
    *,
    title: str,
    category: str,
    sections: tuple[StructuredSection, ...],
) -> tuple[QueryScopeName, ...]:
    haystack = normalize_cell_text(
        "\n".join(
            [
                title,
                category,
                *(section.heading for section in sections[:12]),
            ]
        )
    ).casefold()
    matched_scopes: list[QueryScopeName] = []
    for rule in SCOPE_RULES:
        if any(fragment in haystack for fragment in rule.contains_any):
            if rule.scope not in matched_scopes:
                matched_scopes.append(rule.scope)

    if not matched_scopes:
        return ("general",)

    ordered = sorted(
        matched_scopes,
        key=lambda scope: (
            max(rule.priority for rule in SCOPE_RULES if rule.scope == scope),
            scope,
        ),
        reverse=True,
    )
    return tuple(ordered)


def _match_section(
    text: str,
    sections: tuple[StructuredSection, ...],
) -> StructuredSection | None:
    if not sections:
        return None

    query_tokens = tokenize_text(text)
    ranked_sections: list[tuple[int, StructuredSection]] = []
    for section in sections:
        section_tokens = tokenize_text(f"{section.heading}\n{section.body}")
        score = token_overlap_score(query_tokens, section_tokens)
        if score > 0:
            ranked_sections.append((score, section))

    if ranked_sections:
        ranked_sections.sort(key=lambda item: (-item[0], len(item[1].heading_path)))
        return ranked_sections[0][1]

    for section in sections:
        if section.body:
            return section
    return sections[0]

