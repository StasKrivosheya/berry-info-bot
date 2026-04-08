# ruff: noqa: RUF001

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.services.knowledge_base.query.execution_strategies import (
    build_comparison_result,
    build_enumeration_result,
    build_overview_result,
    dedupe,
    document_support,
    extract_section_items,
)
from app.services.knowledge_base.query.execution_trace import (
    with_retrieval_trace as _with_retrieval_trace,
)
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
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
DETAIL_FACET_TIME = "time"
DETAIL_FACET_PRICE = "price"
DETAIL_FACET_AVAILABILITY = "availability"
DETAIL_FACET_LOCATION = "location"
DETAIL_FACET_ANIMALS = "animals"
TIME_QUERY_HINTS = (
    "коли",
    "відкривається",
    "відкриваєтесь",
    "працює",
    "графік",
    "час",
    "годин",
)
TIME_SECTION_HINTS = (
    "графік роботи",
    "час роботи",
    "парк працює",
    "працює",
    "з 10:00",
    "до 19:00",
)
PRICE_QUERY_HINTS = ("скільки", "вартість", "ціна", "коштує", "грн")
PRICE_SECTION_HINTS = ("вартість", "ціна", "грн", "квит")
AVAILABILITY_QUERY_HINTS = ("чи є", "є у вас", "можна", "доступно")
LOCATION_QUERY_HINTS = ("де", "як доїхати", "трансфер", "адрес")
ANIMAL_QUERY_HINTS = (
    "тварин",
    "тваринки",
    "тварини",
    "зоопарк",
    "звірят",
    "ранчо",
)
ANIMAL_SECTION_HINTS = (
    "тварин",
    "тваринки",
    "поні-ферм",
    "ферма до тваринок",
    "ранчо",
    "альпак",
    "козлик",
    "поні",
)
GENERIC_TIME_PENALTIES = (
    "додаткові послуги",
    "послуги на території",
    "вартість",
)
GENERIC_ANIMAL_PENALTIES = (
    "додаткові послуги",
    "послуги на території",
    "водні розваги",
    "вартість",
)
GENERIC_SUPPORT_TOKEN_KEYS = frozenset(
    {
        "скільк",
        "коштує",
        "вартіс",
        "ціна",
        "коли",
        "відкри",
        "працює",
        "графік",
        "час",
        "можна",
        "де",
        "які",
        "який",
        "що",
        "хто",
        "є",
        "чи",
        "маєте",
        "мають",
        "розкаж",
        "порадь",
    }
)
MIN_RETRIEVAL_QUERY_CONFIDENCE_FOR_RANKING = 0.7
MIN_RETRIEVAL_SUPPORT_COVERAGE = 0.5


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
        result = build_enumeration_result(plan, documents)
        if result is not None:
            if result.retrieval_trace is None:
                result = _with_retrieval_trace(result, retrieval_trace)
            return result
    elif plan.strategy == "overview_summary":
        result = build_overview_result(plan, documents)
        if result is not None:
            if result.retrieval_trace is None:
                result = _with_retrieval_trace(result, retrieval_trace)
            return result
    elif plan.strategy == "comparison_summary":
        result = build_comparison_result(plan, query, documents, search_response)
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
            retrieval_trace=retrieval_trace,
        )
        if detail_result is not None:
            return detail_result

    result = _build_safe_fallback_result(
        plan,
        query,
        documents,
        search_response,
        structure_reader=structure_reader,
        detail_result=detail_result,
        detail_attempted=detail_attempted,
        retrieval_trace=retrieval_trace,
    )
    if result.retrieval_trace is None:
        result = _with_retrieval_trace(result, retrieval_trace)
    return result


def _build_detail_result(
    plan: QueryPlan,
    query: str,
    documents: tuple[StructuredDocument, ...],
    search_response: SearchResponse | None,
    *,
    structure_reader: KnowledgeBaseStructureReader,
    retrieval_trace: QueryRetrievalExecutionTrace | None = None,
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
    detail_facet = _detect_detail_facet(query_text)
    ranking_tokens = (
        tuple(dict.fromkeys((*query_tokens, *_retrieval_ranking_tokens(plan))))
        if _should_expand_ranking_tokens(plan)
        else query_tokens
    )
    support = document_support(search_response)
    documents_by_id = {document.logical_id: document for document in documents}
    _log_structure_mapping(search_response, documents_by_id, structure_reader)
    if not _search_response_supports_query(
        search_response,
        plan,
        query_tokens,
        documents_by_id,
    ):
        unsupported_result = QueryAnswerResult(
            plan=plan,
            summary=NO_RELEVANT_INFO_FALLBACK,
            blocks=(),
            sources=(),
            search_response=search_response,
            fallback_used=True,
        )
        return _with_retrieval_trace(
            unsupported_result,
            retrieval_trace,
            trusted_top_hit=False,
            note="no_specific_query_evidence_in_hits",
        )
    blocks: list[AnswerBlock] = []
    sources: list[str] = []
    seen_block_keys: set[tuple[str, tuple[str, ...] | str]] = set()
    trusted_top_hit = False
    renderer_note = "no_hit_anchored_block"

    for index, hit in enumerate(search_response.results):
        logical_id = _search_hit_logical_id(hit)
        document = documents_by_id.get(logical_id)
        hit_context = _resolve_hit_context(structure_reader, hit)
        block = None
        block_key: tuple[str, tuple[str, ...] | str] | None = None

        if document is not None:
            section = _select_best_section_for_hit(
                document,
                hit_context=hit_context,
                query_text=query_text,
                query_tokens=ranking_tokens,
                support_score=support.get(logical_id, 0.0),
                detail_facet=detail_facet,
            )
            if section is not None:
                block_key = (document.logical_id, section.heading_path)
                if block_key not in seen_block_keys:
                    block = _detail_block(document, section, ranking_tokens, detail_facet)
                    if block is not None and index == 0:
                        trusted_top_hit = True
                        renderer_note = "used_hit_anchored_section"

        if block is None:
            raw_title = _raw_hit_title(hit, hit_context)
            block_key = (logical_id, raw_title)
            if block_key not in seen_block_keys:
                block = _raw_hit_detail_block(
                    hit,
                    raw_title=raw_title,
                    query_tokens=ranking_tokens,
                    detail_facet=detail_facet,
                )
                if block is not None and index == 0:
                    trusted_top_hit = True
                    renderer_note = "used_top_hit_raw_lines"

        if block is None or block_key is None:
            continue
        seen_block_keys.add(block_key)
        blocks.append(block)
        sources.append(logical_id)
        if len(blocks) >= 2:
            break

    if not blocks:
        return None

    result = QueryAnswerResult(
        plan=plan,
        summary="Знайшов найближчі розділи:",
        blocks=tuple(blocks),
        sources=tuple(dedupe(sources)),
        search_response=search_response,
        fallback_used=False,
    )
    return _with_retrieval_trace(
        result,
        retrieval_trace,
        trusted_top_hit=trusted_top_hit,
        note=renderer_note,
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
    retrieval_trace: QueryRetrievalExecutionTrace | None = None,
) -> QueryAnswerResult:
    if detail_result is None and not detail_attempted:
        detail_result = _build_detail_result(
            plan,
            query,
            documents,
            search_response,
            structure_reader=structure_reader,
            retrieval_trace=retrieval_trace,
        )
    if detail_result is not None:
        if not detail_result.blocks and detail_result.summary == NO_RELEVANT_INFO_FALLBACK:
            return detail_result
        return QueryAnswerResult(
            plan=plan,
            summary="Не вдалося впевнено класифікувати запит. Показую найближчі розділи:",
            blocks=detail_result.blocks,
            sources=detail_result.sources,
            search_response=search_response,
            fallback_used=True,
            retrieval_trace=detail_result.retrieval_trace,
        )

    raw_hit_result = _build_raw_hit_fallback_result(
        plan,
        query,
        search_response,
        structure_reader=structure_reader,
        retrieval_trace=retrieval_trace,
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

def _detail_block(
    document: StructuredDocument,
    section: StructuredSection,
    query_tokens: tuple[str, ...],
    detail_facet: str | None,
) -> AnswerBlock | None:
    items = extract_section_items(section.body)
    ranked_items: list[tuple[int, str]] = []
    for item in items:
        score = token_overlap_score(query_tokens, tokenize_text(item))
        score += _detail_item_bonus(item, detail_facet)
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
    retrieval_trace: QueryRetrievalExecutionTrace | None = None,
) -> QueryAnswerResult | None:
    if search_response is None or not search_response.results:
        return None

    query_tokens = tokenize_text(query)
    detail_facet = _detect_detail_facet(normalize_query_text(query))
    ranking_tokens = (
        tuple(dict.fromkeys((*query_tokens, *_retrieval_ranking_tokens(plan))))
        if _should_expand_ranking_tokens(plan)
        else query_tokens
    )
    blocks: list[AnswerBlock] = []
    sources: list[str] = []
    seen_blocks: set[tuple[str, str]] = set()
    trusted_top_hit = False
    renderer_note = "no_raw_hit_lines"

    for hit in search_response.results:
        logical_id = _search_hit_logical_id(hit)
        hit_context = _resolve_hit_context(structure_reader, hit)
        title = _raw_hit_title(hit, hit_context)
        block_key = (logical_id, title)
        if block_key in seen_blocks:
            continue

        lines = _rank_hit_lines(hit.text, ranking_tokens, detail_facet)
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
        if not trusted_top_hit:
            trusted_top_hit = True
            renderer_note = "used_top_hit_raw_lines"
        if len(blocks) >= 2:
            break

    if not blocks:
        return None

    logger.debug(
        "%s block_count=%s source_count=%s",
        LOG_EVENT_RAW_DETAIL_FALLBACK,
        len(blocks),
        len(dedupe(sources)),
    )
    result = QueryAnswerResult(
        plan=plan,
        summary="Не вдалося побудувати структуровану відповідь. Показую найближчі сирі збіги:",
        blocks=tuple(blocks),
        sources=tuple(dedupe(sources)),
        search_response=search_response,
        fallback_used=True,
    )
    return _with_retrieval_trace(
        result,
        retrieval_trace,
        trusted_top_hit=trusted_top_hit,
        note=renderer_note,
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


def _rank_hit_lines(
    text: str,
    query_tokens: tuple[str, ...],
    detail_facet: str | None = None,
) -> list[str]:
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
        overlap += _detail_item_bonus(cleaned, detail_facet)
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


def _should_expand_ranking_tokens(plan: QueryPlan) -> bool:
    return (
        plan.policy_trace.mode == "forced"
        or plan.retrieval_plan.confidence >= MIN_RETRIEVAL_QUERY_CONFIDENCE_FOR_RANKING
    )


def _search_response_supports_query(
    search_response: SearchResponse,
    plan: QueryPlan,
    query_tokens: tuple[str, ...],
    documents_by_id: dict[str, StructuredDocument],
) -> bool:
    content_tokens = _content_support_tokens(query_tokens)
    if not content_tokens:
        return True

    search_tokens = _search_response_tokens(search_response, documents_by_id)
    query_coverage = _token_coverage(content_tokens, search_tokens)
    if query_coverage >= 1.0:
        return True

    if plan.retrieval_plan.confidence < MIN_RETRIEVAL_QUERY_CONFIDENCE_FOR_RANKING:
        return False

    retrieval_tokens = _content_support_tokens(
        tokenize_text("\n".join(plan.retrieval_plan.keywords))
    )
    if not retrieval_tokens:
        retrieval_tokens = _content_support_tokens(
            tokenize_text("\n".join(plan.retrieval_plan.alternate_queries))
        )
    if not retrieval_tokens:
        return False

    retrieval_coverage = _token_coverage(retrieval_tokens, search_tokens)
    return retrieval_coverage >= MIN_RETRIEVAL_SUPPORT_COVERAGE


def _content_support_tokens(tokens: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            token for token in tokens if token and token not in GENERIC_SUPPORT_TOKEN_KEYS
        )
    )


def _search_response_tokens(
    search_response: SearchResponse,
    documents_by_id: dict[str, StructuredDocument],
) -> set[str]:
    tokens: set[str] = set()
    document_tokens: dict[str, set[str]] = {}
    for hit in search_response.results[:5]:
        tokens.update(tokenize_text(f"{hit.filename}\n{hit.text}"))
        document = documents_by_id.get(_search_hit_logical_id(hit))
        if document is None:
            continue
        cached = document_tokens.get(document.logical_id)
        if cached is None:
            cached = {
                token
                for section in document.sections
                for token in tokenize_text(f"{section.heading}\n{section.body}")
            }
            document_tokens[document.logical_id] = cached
        tokens.update(cached)
    return tokens


def _token_coverage(tokens: tuple[str, ...], haystack: set[str]) -> float:
    if not tokens:
        return 0.0
    matched = sum(1 for token in tokens if token in haystack)
    return matched / len(tokens)


def _select_best_section_for_hit(
    document: StructuredDocument,
    *,
    hit_context: SearchHitDebugContext | None,
    query_text: str,
    query_tokens: tuple[str, ...],
    support_score: float,
    detail_facet: str | None,
) -> StructuredSection | None:
    hit_path = hit_context.heading_path if hit_context is not None else ()
    ranked_sections: list[tuple[float, StructuredSection]] = []
    for section in document.sections:
        score = _score_section(
            query_text=query_text,
            query_tokens=query_tokens,
            section=section,
            support_score=support_score,
        )
        score += _hit_anchor_bonus(section.heading_path, hit_path, detail_facet)
        score += _detail_section_bonus(section, detail_facet)
        score -= _detail_section_penalty(section, detail_facet)
        if score <= 0:
            continue
        ranked_sections.append((score, section))
    if not ranked_sections:
        return None
    ranked_sections.sort(key=lambda item: (-item[0], len(item[1].heading_path)))
    return ranked_sections[0][1]


def _raw_hit_detail_block(
    hit: SearchHit,
    *,
    raw_title: str,
    query_tokens: tuple[str, ...],
    detail_facet: str | None,
) -> AnswerBlock | None:
    lines = _rank_hit_lines(hit.text, query_tokens, detail_facet)
    if lines:
        return AnswerBlock(title=raw_title, lines=tuple(lines))
    excerpt = shorten_text(hit.text, limit=420)
    if excerpt:
        return AnswerBlock(title=raw_title, body=excerpt)
    return None


def _detect_detail_facet(query_text: str) -> str | None:
    if any(hint in query_text for hint in TIME_QUERY_HINTS):
        return DETAIL_FACET_TIME
    if any(hint in query_text for hint in PRICE_QUERY_HINTS):
        return DETAIL_FACET_PRICE
    if any(hint in query_text for hint in ANIMAL_QUERY_HINTS):
        return DETAIL_FACET_ANIMALS
    if any(hint in query_text for hint in LOCATION_QUERY_HINTS):
        return DETAIL_FACET_LOCATION
    if any(hint in query_text for hint in AVAILABILITY_QUERY_HINTS):
        return DETAIL_FACET_AVAILABILITY
    return None


def _detail_section_bonus(section: StructuredSection, detail_facet: str | None) -> int:
    heading = section.heading.casefold()
    body = section.body.casefold()
    if detail_facet == DETAIL_FACET_TIME:
        score = 0
        if any(hint in heading for hint in TIME_SECTION_HINTS):
            score += 14
        if any(hint in body for hint in TIME_SECTION_HINTS):
            score += 10
        if TIME_RE.search(section.body):
            score += 8
        return score
    if detail_facet == DETAIL_FACET_PRICE:
        score = 0
        if any(hint in heading for hint in PRICE_SECTION_HINTS):
            score += 12
        if any(hint in body for hint in PRICE_SECTION_HINTS):
            score += 8
        return score
    if detail_facet == DETAIL_FACET_ANIMALS:
        score = 0
        if any(hint in heading for hint in ANIMAL_SECTION_HINTS):
            score += 14
        if any(hint in body for hint in ANIMAL_SECTION_HINTS):
            score += 10
        if any(hint in body for hint in ("тварин", "козлик", "альпак", "мешкан")):
            score += 12
        return score
    return 0


def _detail_section_penalty(section: StructuredSection, detail_facet: str | None) -> int:
    if detail_facet != DETAIL_FACET_TIME:
        if detail_facet != DETAIL_FACET_ANIMALS:
            return 0
        heading = section.heading.casefold()
        body = section.body.casefold()
        penalty = 0
        if any(hint in heading for hint in GENERIC_ANIMAL_PENALTIES):
            penalty += 12
        if not any(hint in f"{heading}\n{body}" for hint in ANIMAL_SECTION_HINTS):
            penalty += 10
        if not any(hint in body for hint in ("тварин", "козлик", "альпак", "мешкан")):
            penalty += 8
        return penalty
    heading = section.heading.casefold()
    if any(hint in heading for hint in GENERIC_TIME_PENALTIES):
        return 12
    return 0


def _detail_item_bonus(text: str, detail_facet: str | None) -> int:
    normalized = normalize_query_text(text)
    if detail_facet == DETAIL_FACET_TIME:
        score = 0
        if any(hint in normalized for hint in TIME_SECTION_HINTS):
            score += 8
        if TIME_RE.search(text):
            score += 6
        return score
    if detail_facet == DETAIL_FACET_PRICE:
        if any(hint in normalized for hint in PRICE_SECTION_HINTS):
            return 6
    if detail_facet == DETAIL_FACET_ANIMALS:
        score = 0
        if any(hint in normalized for hint in ANIMAL_SECTION_HINTS):
            score += 8
        return score
    return 0


def _hit_anchor_bonus(
    section_path: tuple[str, ...],
    hit_path: tuple[str, ...],
    detail_facet: str | None,
) -> int:
    if not hit_path:
        return 0
    if section_path == hit_path:
        return 8 if detail_facet == DETAIL_FACET_ANIMALS else 20
    if len(hit_path) > 1 and section_path == hit_path[: len(section_path)]:
        return 8
    if len(section_path) > 1 and len(hit_path) > 1 and section_path[:-1] == hit_path[:-1]:
        return 5
    if section_path[:1] == hit_path[:1]:
        return 2
    return 0
