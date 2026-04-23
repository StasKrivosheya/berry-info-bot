# ruff: noqa: RUF001

from __future__ import annotations

from app.services.knowledge_base.query.answering_models import AnswerDraft
from app.services.knowledge_base.query.dto import VectorHit
from app.services.knowledge_base.query.renderer import AnswerBlock
from app.services.knowledge_base.query.text import (
    shorten_text,
    strip_leading_markers,
    token_overlap_score,
    tokenize_text,
)
from app.services.knowledge_base.query.types import (
    QueryRouteContext,
    StructuredDocument,
    StructuredSection,
)
from app.services.knowledge_base.utils import dedupe_preserve_order

PROGRAM_HEADING_EXCLUDES = (
    "види програм",
    "детальний опис",
    "детальніший опис",
    "детальніше опис",
    "вартість",
    "додаткові послуги",
    "тривалість",
    "трансфер",
    "бронювання",
    "підтвердження",
    "приклад повідомлення",
)
PROGRAM_CATALOG_HEADING_HINTS = ("види програм",)
PROGRAM_CATALOG_BOUNDARY_HINTS = (
    "додаткові послуги",
    "трансфер",
    "бронювання",
    "підтвердження",
    "приклад повідомлення",
)

PARK_SECTION_HINTS = (
    "що входить",
    "що у програмі",
    "активності",
    "розваги",
)
SERVICE_SECTION_HINTS = (
    "додаткові послуги",
    "послуги",
)
FOOD_SECTION_HINTS = (
    "харчування",
    "їжа",
    "кафе",
)


def build_enumeration_result(
    plan: QueryRouteContext,
    documents: tuple[StructuredDocument, ...],
) -> AnswerDraft | None:
    if not documents:
        return None

    if plan.scope_detection.primary_scope == "programs":
        items, sources = _collect_program_names(documents)
        summary = "Знайшов такі організовані програми:"
        title = "Програми"
    else:
        items, sources = _collect_section_titles(documents)
        summary = "Знайшов такі позиції:"
        title = "Позиції"

    if not items:
        return None

    return AnswerDraft(
        summary=summary,
        blocks=(AnswerBlock(title=title, lines=tuple(items[:12])),),
        sources=tuple(sources),
    )


def build_overview_result(
    plan: QueryRouteContext,
    documents: tuple[StructuredDocument, ...],
) -> AnswerDraft | None:
    if not documents:
        return None

    requested_scopes = plan.scope_detection.scopes
    if "general" in requested_scopes:
        requested_scopes = ("programs", "park_activities", "services")

    blocks: list[AnswerBlock] = []
    sources: list[str] = []
    used_sections: set[tuple[str, tuple[str, ...]]] = set()

    if "programs" in requested_scopes:
        items, block_sources = _collect_program_names(documents)
        if items:
            blocks.append(
                AnswerBlock(
                    title="Організовані програми",
                    lines=tuple(items[:8]),
                )
            )
            sources.extend(block_sources)

    if "park_activities" in requested_scopes or "general" in requested_scopes:
        items, block_sources = _collect_section_items(
            documents,
            heading_hints=PARK_SECTION_HINTS,
            limit=6,
            allow_fallback=True,
            used_sections=used_sections,
        )
        if items:
            blocks.append(AnswerBlock(title="У парку можна", lines=tuple(items)))
            sources.extend(block_sources)

    if "services" in requested_scopes or "general" in requested_scopes:
        items, block_sources = _collect_section_items(
            documents,
            heading_hints=SERVICE_SECTION_HINTS,
            limit=5,
            allow_fallback=True,
            used_sections=used_sections,
        )
        if items:
            blocks.append(AnswerBlock(title="Додаткові послуги", lines=tuple(items)))
            sources.extend(block_sources)

    if "food" in requested_scopes:
        items, block_sources = _collect_section_items(
            documents,
            heading_hints=FOOD_SECTION_HINTS,
            limit=5,
            allow_fallback=True,
            used_sections=used_sections,
        )
        if items:
            blocks.append(AnswerBlock(title="Їжа та харчування", lines=tuple(items)))
            sources.extend(block_sources)

    if not blocks:
        return None

    return AnswerDraft(
        summary="Знайшов кілька основних варіантів у Berry Land.",
        blocks=tuple(blocks),
        sources=tuple(dedupe(sources)),
    )


def build_comparison_result(
    plan: QueryRouteContext,
    query: str,
    documents: tuple[StructuredDocument, ...],
    vector_hits: tuple[VectorHit, ...],
) -> AnswerDraft | None:
    del plan
    if not documents or not vector_hits:
        return None

    documents_by_id = {document.logical_id: document for document in documents}
    candidate_ids = dedupe(list(document_support(vector_hits).keys()))[:2]
    blocks: list[AnswerBlock] = []
    sources: list[str] = []

    for logical_id in candidate_ids:
        document = documents_by_id.get(logical_id)
        if document is None:
            continue
        lines = _comparison_lines(document, query)
        if not lines:
            continue
        blocks.append(AnswerBlock(title=document.title, lines=tuple(lines)))
        sources.append(document.logical_id)

    if len(blocks) < 2:
        return None

    return AnswerDraft(
        summary="Знайшов такі варіанти для порівняння:",
        blocks=tuple(blocks),
        sources=tuple(dedupe(sources)),
    )


def extract_section_items(body: str) -> list[str]:
    items: list[str] = []
    for raw_line in body.splitlines():
        cleaned = strip_leading_markers(raw_line)
        if len(cleaned) < 3:
            continue
        if cleaned.casefold() == "або":
            continue
        items.append(shorten_text(cleaned))
    return items


def document_support(vector_hits: tuple[VectorHit, ...]) -> dict[str, float]:
    support: dict[str, float] = {}
    for hit in vector_hits:
        logical_id = (
            str(hit.attributes.get("logical_id", "")).strip() or hit.section_id.split(":", 1)[0]
        )
        support[logical_id] = max(support.get(logical_id, 0.0), hit.score)
    return support


def dedupe(values: list[str]) -> list[str]:
    return dedupe_preserve_order(values)


def _collect_program_names(
    documents: tuple[StructuredDocument, ...],
) -> tuple[list[str], list[str]]:
    names: list[str] = []
    sources: list[str] = []
    seen_names: set[str] = set()

    for document in documents:
        if not _looks_like_program_document(document):
            continue
        used_document = False
        catalog_active = _document_starts_with_program_catalog(document)
        for section in document.sections:
            if section.level != 2:
                continue
            heading = section.heading.casefold()
            if _is_program_catalog_heading(heading):
                catalog_active = True
                continue
            if catalog_active and _is_program_catalog_boundary(heading):
                catalog_active = False
                continue
            if not catalog_active or not _looks_like_program_name(section.heading):
                continue
            key = section.heading.casefold()
            if key in seen_names:
                continue
            seen_names.add(key)
            names.append(section.heading)
            used_document = True
        if used_document:
            sources.append(document.logical_id)

    return names, dedupe(sources)


def _collect_section_titles(
    documents: tuple[StructuredDocument, ...],
) -> tuple[list[str], list[str]]:
    titles: list[str] = []
    sources: list[str] = []
    seen_titles: set[str] = set()

    for document in documents:
        used_document = False
        for section in document.sections:
            if section.level > 3:
                continue
            if len(section.heading) < 3:
                continue
            key = section.heading.casefold()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            titles.append(section.heading)
            used_document = True
        if used_document:
            sources.append(document.logical_id)

    return titles, dedupe(sources)


def _collect_section_items(
    documents: tuple[StructuredDocument, ...],
    *,
    heading_hints: tuple[str, ...],
    limit: int,
    allow_fallback: bool = False,
    used_sections: set[tuple[str, tuple[str, ...]]] | None = None,
) -> tuple[list[str], list[str]]:
    items: list[str] = []
    sources: list[str] = []
    seen_items: set[str] = set()

    def collect(*, fallback_mode: bool) -> None:
        for document in documents:
            used_document = False
            for section in document.sections:
                section_key = (document.logical_id, section.heading_path)
                if used_sections is not None and section_key in used_sections:
                    continue
                heading = section.heading.casefold()
                if not fallback_mode and not any(hint in heading for hint in heading_hints):
                    continue
                section_items = extract_section_items(section.body)
                if not section_items:
                    continue
                for item in section_items:
                    key = item.casefold()
                    if key in seen_items:
                        continue
                    seen_items.add(key)
                    items.append(item)
                    used_document = True
                    if len(items) >= limit:
                        break
                if used_document and used_sections is not None:
                    used_sections.add(section_key)
                if used_document or len(items) >= limit:
                    break
            if used_document:
                sources.append(document.logical_id)
                break
            if len(items) >= limit:
                break

    collect(fallback_mode=False)
    if not items and allow_fallback:
        collect(fallback_mode=True)

    return items, dedupe(sources)


def _comparison_lines(document: StructuredDocument, query: str) -> list[str]:
    lines: list[str] = []
    query_tokens = tokenize_text(query)
    ranked_sections: list[tuple[int, StructuredSection]] = []

    for section in document.sections:
        score = token_overlap_score(
            query_tokens,
            tokenize_text(f"{section.heading}\n{section.body}"),
        )
        if score > 0:
            ranked_sections.append((score, section))

    ranked_sections.sort(key=lambda item: (-item[0], item[1].heading.casefold()))
    chosen_sections = [section for _, section in ranked_sections[:2]]
    if not chosen_sections:
        chosen_sections = [section for section in document.sections if section.body][:2]

    for section in chosen_sections:
        items = extract_section_items(section.body)[:3]
        if items:
            lines.extend(items)
            continue
        excerpt = shorten_text(section.body, limit=140)
        if excerpt:
            lines.append(excerpt)

    return dedupe(lines)[:4]


def _looks_like_program_document(document: StructuredDocument) -> bool:
    if document.category == "programs":
        return True
    title = document.title.casefold()
    if "програм" in title:
        return True
    return any("види програм" in section.heading.casefold() for section in document.sections[:4])


def _document_starts_with_program_catalog(document: StructuredDocument) -> bool:
    return any(hint in document.title.casefold() for hint in PROGRAM_CATALOG_HEADING_HINTS)


def _is_program_catalog_heading(heading: str) -> bool:
    return any(hint in heading for hint in PROGRAM_CATALOG_HEADING_HINTS)


def _is_program_catalog_boundary(heading: str) -> bool:
    return any(hint in heading for hint in PROGRAM_CATALOG_BOUNDARY_HINTS)


def _looks_like_program_name(heading: str) -> bool:
    normalized = heading.strip()
    folded = normalized.casefold()
    if len(normalized) < 4 or normalized.isdigit():
        return False
    if any(fragment in folded for fragment in PROGRAM_HEADING_EXCLUDES):
        return False
    return bool(tokenize_text(normalized))
