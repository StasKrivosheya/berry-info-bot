# ruff: noqa: RUF001

from __future__ import annotations

from app.services.knowledge_base.query.text import (
    shorten_text,
    strip_leading_markers,
    token_overlap_score,
    tokenize_text,
)
from app.services.knowledge_base.query.types import (
    AnswerBlock,
    QueryAnswerResult,
    QueryPlan,
    StructuredDocument,
    StructuredSection,
)
from app.services.knowledge_base.types_openai import SearchResponse
from app.services.knowledge_base.utils import dedupe_preserve_order, search_hit_logical_id

PROGRAM_HEADING_EXCLUDES = (
    "види програм",
    "детальний опис",
    "детальніший опис",
    "вартість",
    "додаткові послуги",
    "тривалість",
    "трансфер",
    "бронювання",
    "підтвердження",
    "приклад повідомлення",
)


def build_enumeration_result(
    plan: QueryPlan,
    documents: tuple[StructuredDocument, ...],
) -> QueryAnswerResult | None:
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

    return QueryAnswerResult(
        plan=plan,
        summary=summary,
        blocks=(AnswerBlock(title=title, lines=tuple(items[:12])),),
        sources=tuple(sources),
        search_response=None,
        fallback_used=False,
    )


def build_overview_result(
    plan: QueryPlan,
    documents: tuple[StructuredDocument, ...],
) -> QueryAnswerResult | None:
    if not documents:
        return None

    requested_scopes = plan.scope_detection.scopes
    if "general" in requested_scopes:
        requested_scopes = ("programs", "park_activities", "services")

    blocks: list[AnswerBlock] = []
    sources: list[str] = []

    if "programs" in requested_scopes:
        items, block_sources = _collect_program_names(documents)
        if items:
            blocks.append(AnswerBlock(title="Організовані програми", lines=tuple(items[:8])))
            sources.extend(block_sources)

    if "park_activities" in requested_scopes or "general" in requested_scopes:
        items, block_sources = _collect_section_items(
            documents,
            heading_hints=("що входить", "що у програмі"),
            limit=6,
        )
        if items:
            blocks.append(AnswerBlock(title="У парку можна", lines=tuple(items)))
            sources.extend(block_sources)

    if "services" in requested_scopes or "general" in requested_scopes:
        items, block_sources = _collect_section_items(
            documents,
            heading_hints=("додаткові послуги", "послуги на території парку"),
            limit=5,
        )
        if items:
            blocks.append(AnswerBlock(title="Додаткові послуги", lines=tuple(items)))
            sources.extend(block_sources)

    if "food" in requested_scopes:
        items, block_sources = _collect_section_items(
            documents,
            heading_hints=("харчування", "частування"),
            limit=5,
        )
        if items:
            blocks.append(AnswerBlock(title="Їжа та харчування", lines=tuple(items)))
            sources.extend(block_sources)

    if not blocks:
        return None

    return QueryAnswerResult(
        plan=plan,
        summary="Знайшов кілька основних варіантів у Berry Land.",
        blocks=tuple(blocks),
        sources=tuple(dedupe(sources)),
        search_response=None,
        fallback_used=False,
    )


def build_comparison_result(
    plan: QueryPlan,
    query: str,
    documents: tuple[StructuredDocument, ...],
    search_response: SearchResponse | None,
) -> QueryAnswerResult | None:
    if not documents or search_response is None or not search_response.results:
        return None

    documents_by_id = {document.logical_id: document for document in documents}
    candidate_ids = dedupe(list(document_support(search_response).keys()))[:2]
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

    return QueryAnswerResult(
        plan=plan,
        summary="Знайшов такі варіанти для порівняння:",
        blocks=tuple(blocks),
        sources=tuple(dedupe(sources)),
        search_response=search_response,
        fallback_used=False,
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


def document_support(search_response: SearchResponse) -> dict[str, float]:
    support: dict[str, float] = {}
    for hit in search_response.results:
        logical_id = search_hit_logical_id(hit)
        previous = support.get(logical_id, 0.0)
        support[logical_id] = max(previous, hit.score)
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
        for section in document.sections:
            if section.level != 2:
                continue
            if not _looks_like_program_name(section.heading):
                continue
            normalized = section.heading
            key = normalized.casefold()
            if key in seen_names:
                continue
            seen_names.add(key)
            names.append(normalized)
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
            normalized = section.heading
            key = normalized.casefold()
            if key in seen_titles:
                continue
            if len(normalized) < 3:
                continue
            seen_titles.add(key)
            titles.append(normalized)
            used_document = True
        if used_document:
            sources.append(document.logical_id)
    return titles, dedupe(sources)


def _collect_section_items(
    documents: tuple[StructuredDocument, ...],
    *,
    heading_hints: tuple[str, ...],
    limit: int,
) -> tuple[list[str], list[str]]:
    items: list[str] = []
    sources: list[str] = []
    seen_items: set[str] = set()

    for document in documents:
        used_document = False
        for section in document.sections:
            heading = section.heading.casefold()
            if not any(hint in heading for hint in heading_hints):
                continue
            for item in extract_section_items(section.body):
                key = item.casefold()
                if key in seen_items:
                    continue
                seen_items.add(key)
                items.append(item)
                used_document = True
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
        if used_document:
            sources.append(document.logical_id)
        if len(items) >= limit:
            break

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
        else:
            excerpt = shorten_text(section.body, limit=140)
            if excerpt:
                lines.append(excerpt)
    return dedupe(lines)[:4]


def _looks_like_program_document(document: StructuredDocument) -> bool:
    title = document.title.casefold()
    if "програм" in title or "організован" in title:
        return True
    return any("види програм" in section.heading.casefold() for section in document.sections[:4])


def _looks_like_program_name(heading: str) -> bool:
    normalized = heading
    folded = normalized.casefold()
    if len(normalized) < 4 or normalized.isdigit():
        return False
    if any(fragment in folded for fragment in PROGRAM_HEADING_EXCLUDES):
        return False
    return bool(tokenize_text(normalized))
