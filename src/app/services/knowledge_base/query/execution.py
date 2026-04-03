# ruff: noqa: RUF001

from __future__ import annotations

import logging
from pathlib import Path

from app.services.knowledge_base.query.structure import KnowledgeBaseStructureReader
from app.services.knowledge_base.query.text import (
    normalize_query_text,
    shorten_text,
    strip_leading_markers,
    token_overlap_score,
    tokenize_text,
)
from app.services.knowledge_base.query.types import (
    AnswerBlock,
    QueryAnswerResult,
    QueryPlan,
    QueryRetrievalExecutionTrace,
    SearchHitDebugContext,
    StructuredDocument,
    StructuredSection,
)
from app.services.knowledge_base.types_openai import (
    NO_RELEVANT_INFO_FALLBACK,
    SearchHit,
    SearchResponse,
)

logger = logging.getLogger(__name__)

LOG_EVENT_QUERY_EXECUTION = "kb_query_execution"
LOG_EVENT_DETAIL_RESULT_SKIPPED = "kb_query_detail_result_skipped"
LOG_EVENT_STRUCTURE_MAPPING = "kb_query_structure_mapping"
LOG_EVENT_RAW_DETAIL_FALLBACK = "kb_query_raw_detail_fallback"

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


def execute_query_plan(
    query: str,
    plan: QueryPlan,
    *,
    structure_reader: KnowledgeBaseStructureReader,
    search_response: SearchResponse | None = None,
    retrieval_trace: QueryRetrievalExecutionTrace | None = None,
) -> QueryAnswerResult:
    documents = (
        structure_reader.documents_for_scopes(plan.scope_detection.scopes)
        if plan.needs_structure
        else ()
    )
    logger.debug(
        (
            "%s query=%r intent=%s scope=%s strategy=%s "
            "structured_document_count=%s retrieval_hit_count=%s manifest=%s"
        ),
        LOG_EVENT_QUERY_EXECUTION,
        query,
        plan.intent,
        plan.scope_detection.primary_scope,
        plan.strategy,
        len(documents),
        len(search_response.results) if search_response is not None else 0,
        structure_reader.manifest_path.as_posix(),
    )
    detail_result = None
    detail_attempted = False

    if plan.strategy == "enumeration_catalog":
        result = _build_enumeration_result(plan, documents)
        if result is not None:
            if result.retrieval_trace is None:
                result = _with_retrieval_trace(result, retrieval_trace)
            return result
    elif plan.strategy == "overview_summary":
        result = _build_overview_result(plan, documents)
        if result is not None:
            if result.retrieval_trace is None:
                result = _with_retrieval_trace(result, retrieval_trace)
            return result
    elif plan.strategy == "comparison_summary":
        result = _build_comparison_result(plan, query, documents, search_response)
        if result is not None:
            if result.retrieval_trace is None:
                result = _with_retrieval_trace(result, retrieval_trace)
            return result
    elif plan.strategy == "detail_retrieval":
        detail_attempted = True
        detail_result = _build_detail_result(
            plan,
            query,
            documents,
            search_response,
            structure_reader=structure_reader,
        )
        if detail_result is not None:
            if detail_result.retrieval_trace is None:
                detail_result = _with_retrieval_trace(detail_result, retrieval_trace)
            return detail_result

    result = _build_safe_fallback_result(
        plan,
        query,
        documents,
        search_response,
        structure_reader=structure_reader,
        detail_result=detail_result,
        detail_attempted=detail_attempted,
    )
    if result.retrieval_trace is None:
        result = _with_retrieval_trace(result, retrieval_trace)
    return result


def _build_enumeration_result(
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


def _build_overview_result(
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
        sources=tuple(_dedupe(sources)),
        search_response=None,
        fallback_used=False,
    )


def _build_comparison_result(
    plan: QueryPlan,
    query: str,
    documents: tuple[StructuredDocument, ...],
    search_response: SearchResponse | None,
) -> QueryAnswerResult | None:
    if not documents or search_response is None or not search_response.results:
        return None

    documents_by_id = {document.logical_id: document for document in documents}
    candidate_ids = _dedupe(list(_document_support(search_response).keys()))[:2]
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
        sources=tuple(_dedupe(sources)),
        search_response=search_response,
        fallback_used=False,
    )


def _build_detail_result(
    plan: QueryPlan,
    query: str,
    documents: tuple[StructuredDocument, ...],
    search_response: SearchResponse | None,
    *,
    structure_reader: KnowledgeBaseStructureReader,
) -> QueryAnswerResult | None:
    if search_response is None:
        logger.debug("%s reason=no_search_response", LOG_EVENT_DETAIL_RESULT_SKIPPED)
        return None
    if not search_response.results:
        logger.debug("%s reason=no_search_hits", LOG_EVENT_DETAIL_RESULT_SKIPPED)
        return None
    if not documents:
        _log_structure_mapping(search_response, {}, structure_reader)
        logger.debug("%s reason=no_structured_documents", LOG_EVENT_DETAIL_RESULT_SKIPPED)
        return None

    query_text = normalize_query_text(query)
    query_tokens = tokenize_text(query)
    retrieval_tokens = _retrieval_ranking_tokens(plan)
    ranking_tokens = tuple(dict.fromkeys((*query_tokens, *retrieval_tokens)))
    support = _document_support(search_response)
    documents_by_id = {document.logical_id: document for document in documents}
    _log_structure_mapping(search_response, documents_by_id, structure_reader)
    ranked_sections: list[tuple[float, StructuredDocument, StructuredSection]] = []

    for document in documents:
        for section in document.sections:
            score = _score_section(
                query_text=query_text,
                query_tokens=ranking_tokens,
                section=section,
                support_score=support.get(document.logical_id, 0.0),
            )
            if score <= 0:
                continue
            ranked_sections.append((score, document, section))

    if not ranked_sections:
        logger.debug(
            "%s reason=no_ranked_sections query_tokens=%s supported_documents=%s",
            LOG_EVENT_DETAIL_RESULT_SKIPPED,
            query_tokens,
            tuple(sorted(support.keys())),
        )
        return None

    ranked_sections.sort(
        key=lambda item: (-item[0], item[1].logical_id, item[2].heading.casefold())
    )
    blocks: list[AnswerBlock] = []
    sources: list[str] = []
    seen_blocks: set[tuple[str, tuple[str, ...]]] = set()

    for _, document, section in ranked_sections:
        block_key = (document.logical_id, section.heading_path)
        if block_key in seen_blocks:
            continue
        block = _detail_block(document, section, ranking_tokens)
        if block is None:
            continue
        seen_blocks.add(block_key)
        blocks.append(block)
        sources.append(document.logical_id)
        if len(blocks) >= 2:
            break

    if not blocks:
        return None

    return QueryAnswerResult(
        plan=plan,
        summary="Знайшов найближчі розділи:",
        blocks=tuple(blocks),
        sources=tuple(_dedupe(sources)),
        search_response=search_response,
        fallback_used=False,
    )


def _build_safe_fallback_result(
    plan: QueryPlan,
    query: str,
    documents: tuple[StructuredDocument, ...],
    search_response: SearchResponse | None,
    *,
    structure_reader: KnowledgeBaseStructureReader,
    detail_result: QueryAnswerResult | None = None,
    detail_attempted: bool = False,
) -> QueryAnswerResult:
    if detail_result is None and not detail_attempted:
        detail_result = _build_detail_result(
            plan,
            query,
            documents,
            search_response,
            structure_reader=structure_reader,
        )
    if detail_result is not None:
        return QueryAnswerResult(
            plan=plan,
            summary="Не вдалося впевнено класифікувати запит. Показую найближчі розділи:",
            blocks=detail_result.blocks,
            sources=detail_result.sources,
            search_response=search_response,
            fallback_used=True,
        )

    raw_hit_result = _build_raw_hit_fallback_result(
        plan,
        query,
        search_response,
        structure_reader=structure_reader,
    )
    if raw_hit_result is not None:
        return raw_hit_result

    fallback_message = NO_RELEVANT_INFO_FALLBACK
    if search_response is not None and search_response.fallback_message:
        fallback_message = search_response.fallback_message

    return QueryAnswerResult(
        plan=plan,
        summary=fallback_message,
        blocks=(),
        sources=(),
        search_response=search_response,
        fallback_used=True,
    )


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

    return names, _dedupe(sources)


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
    return titles, _dedupe(sources)


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
            for item in _extract_section_items(section.body):
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

    return items, _dedupe(sources)


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
        items = _extract_section_items(section.body)[:3]
        if items:
            lines.extend(items)
        else:
            excerpt = shorten_text(section.body, limit=140)
            if excerpt:
                lines.append(excerpt)
    return _dedupe(lines)[:4]


def _detail_block(
    document: StructuredDocument,
    section: StructuredSection,
    query_tokens: tuple[str, ...],
) -> AnswerBlock | None:
    items = _extract_section_items(section.body)
    ranked_items: list[tuple[int, str]] = []
    for item in items:
        score = token_overlap_score(query_tokens, tokenize_text(item))
        ranked_items.append((score, item))

    ranked_items.sort(key=lambda item: (-item[0], item[1].casefold()))
    selected_items = [item for _, item in ranked_items if item][:4]
    title = " > ".join(section.heading_path) if section.heading_path else document.title

    if selected_items:
        return AnswerBlock(title=title, lines=tuple(selected_items))

    excerpt = shorten_text(section.body, limit=420)
    if excerpt:
        return AnswerBlock(title=title, body=excerpt)
    return None


def _build_raw_hit_fallback_result(
    plan: QueryPlan,
    query: str,
    search_response: SearchResponse | None,
    *,
    structure_reader: KnowledgeBaseStructureReader,
) -> QueryAnswerResult | None:
    if search_response is None or not search_response.results:
        return None

    query_tokens = tokenize_text(query)
    retrieval_tokens = _retrieval_ranking_tokens(plan)
    ranking_tokens = tuple(dict.fromkeys((*query_tokens, *retrieval_tokens)))
    blocks: list[AnswerBlock] = []
    sources: list[str] = []
    seen_blocks: set[tuple[str, str]] = set()

    for hit in search_response.results:
        logical_id = _search_hit_logical_id(hit)
        hit_context = _resolve_hit_context(structure_reader, hit)
        title = _raw_hit_title(hit, hit_context)
        block_key = (logical_id, title)
        if block_key in seen_blocks:
            continue

        lines = _rank_hit_lines(hit.text, ranking_tokens)
        if lines:
            block = AnswerBlock(title=title, lines=tuple(lines))
        else:
            excerpt = shorten_text(hit.text, limit=420)
            if not excerpt:
                continue
            block = AnswerBlock(title=title, body=excerpt)

        seen_blocks.add(block_key)
        blocks.append(block)
        sources.append(logical_id)
        if len(blocks) >= 2:
            break

    if not blocks:
        return None

    logger.debug(
        "%s block_count=%s source_count=%s",
        LOG_EVENT_RAW_DETAIL_FALLBACK,
        len(blocks),
        len(_dedupe(sources)),
    )
    return QueryAnswerResult(
        plan=plan,
        summary="Не вдалося побудувати структуровану відповідь. Показую найближчі сирі збіги:",
        blocks=tuple(blocks),
        sources=tuple(_dedupe(sources)),
        search_response=search_response,
        fallback_used=True,
    )


def _score_section(
    *,
    query_text: str,
    query_tokens: tuple[str, ...],
    section: StructuredSection,
    support_score: float,
) -> float:
    section_text = normalize_query_text(f"{section.heading}\n{section.body}")
    heading_tokens = tokenize_text(section.heading)
    body_tokens = tokenize_text(section.body)

    score = support_score * 10
    score += token_overlap_score(query_tokens, heading_tokens) * 4
    score += token_overlap_score(query_tokens, body_tokens) * 2
    if query_text and len(query_text) >= 4 and query_text in section_text:
        score += 6
    return score


def _extract_section_items(body: str) -> list[str]:
    items: list[str] = []
    for raw_line in body.splitlines():
        cleaned = strip_leading_markers(raw_line)
        if len(cleaned) < 3:
            continue
        if cleaned.casefold() == "або":
            continue
        items.append(shorten_text(cleaned))
    return items


def _document_support(search_response: SearchResponse) -> dict[str, float]:
    support: dict[str, float] = {}
    for hit in search_response.results:
        logical_id = _search_hit_logical_id(hit)
        previous = support.get(logical_id, 0.0)
        support[logical_id] = max(previous, hit.score)
    return support


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


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _log_structure_mapping(
    search_response: SearchResponse,
    documents_by_id: dict[str, StructuredDocument],
    structure_reader: KnowledgeBaseStructureReader,
) -> None:
    for hit in search_response.results:
        logical_id = _search_hit_logical_id(hit)
        hit_context = _resolve_hit_context(structure_reader, hit)
        logger.debug(
            "%s logical_id=%s scoped_document=%s context_resolved=%s heading_path=%s",
            LOG_EVENT_STRUCTURE_MAPPING,
            logical_id,
            logical_id in documents_by_id,
            hit_context is not None,
            hit_context.heading_path if hit_context is not None else (),
        )


def _resolve_hit_context(
    structure_reader: KnowledgeBaseStructureReader,
    hit: SearchHit,
) -> SearchHitDebugContext | None:
    try:
        return structure_reader.resolve_hit_context(hit)
    except Exception:
        logger.debug(
            "%s logical_id=%s resolution_failed=True",
            LOG_EVENT_STRUCTURE_MAPPING,
            _search_hit_logical_id(hit),
            exc_info=True,
        )
        return None


def _rank_hit_lines(text: str, query_tokens: tuple[str, ...]) -> list[str]:
    ranked_lines: list[tuple[int, str]] = []
    fallback_lines: list[str] = []
    seen_lines: set[str] = set()

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        cleaned = strip_leading_markers(raw_line)
        if len(cleaned) < 3:
            continue

        key = cleaned.casefold()
        if key in seen_lines:
            continue
        seen_lines.add(key)

        overlap = token_overlap_score(query_tokens, tokenize_text(cleaned))
        if overlap > 0:
            ranked_lines.append((overlap, cleaned))
            continue
        if len(fallback_lines) < 2:
            fallback_lines.append(cleaned)

    ranked_lines.sort(key=lambda item: (-item[0], item[1].casefold()))
    selected = [line for _, line in ranked_lines[:4]]
    if selected:
        return selected
    return fallback_lines[:2]


def _raw_hit_title(hit: SearchHit, hit_context: SearchHitDebugContext | None) -> str:
    if hit_context is not None and hit_context.heading_path:
        return " > ".join(hit_context.heading_path)
    if hit_context is not None and hit_context.document_title:
        return hit_context.document_title
    return hit.filename


def _search_hit_logical_id(hit: SearchHit) -> str:
    logical_id = str(hit.attributes.get("logical_id", "")).strip()
    return logical_id or Path(hit.filename).stem


def _retrieval_ranking_tokens(plan: QueryPlan) -> tuple[str, ...]:
    token_source = "\n".join(
        (
            plan.retrieval_plan.primary_query,
            "\n".join(plan.retrieval_plan.alternate_queries),
            "\n".join(plan.retrieval_plan.keywords),
        )
    )
    return tokenize_text(token_source)


def _with_retrieval_trace(
    result: QueryAnswerResult,
    retrieval_trace: QueryRetrievalExecutionTrace | None,
) -> QueryAnswerResult:
    return QueryAnswerResult(
        plan=result.plan,
        blocks=result.blocks,
        summary=result.summary,
        sources=result.sources,
        search_response=result.search_response,
        fallback_used=result.fallback_used,
        retrieval_trace=retrieval_trace,
    )
