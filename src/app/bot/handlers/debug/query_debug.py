from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.bot.handlers.debug.vector_search_debug import (
    VS_COMMAND_NAME,
    VS_ERROR_TEXT,
    VS_USAGE_TEXT,
    extract_query_text,
    format_search_messages,
    split_for_telegram,
)
from app.services.knowledge_base.query.pipeline import KnowledgeBaseQueryPipeline
from app.services.knowledge_base.query.renderer import render_query_answer
from app.services.knowledge_base.query.structure import KnowledgeBaseStructureReader
from app.services.knowledge_base.query.types import (
    QueryAnswerResult,
    QueryClassification,
    QueryPlan,
)
from app.services.knowledge_base.retrieval.service import KnowledgeBaseRetrievalService

router = Router(name="query-debug")
logger = logging.getLogger(__name__)

QCLASS_COMMAND_NAME = "qclass"
QPLAN_COMMAND_NAME = "qplan"
QANSWER_COMMAND_NAME = "qanswer"

QCLASS_USAGE_TEXT = "Usage: /qclass <your question>"
QPLAN_USAGE_TEXT = "Usage: /qplan <your question>"
QANSWER_USAGE_TEXT = "Usage: /qanswer <your question>"
QDEBUG_ERROR_TEXT = "Query debug tooling is temporarily unavailable. Please try again later."

LOG_EVENT_BOT_VS_SEARCH_FAILED = "bot_vs_search_failed"
LOG_EVENT_BOT_QDEBUG_FAILED = "bot_qdebug_failed"


def _create_retrieval_service() -> KnowledgeBaseRetrievalService:
    return KnowledgeBaseRetrievalService()


def _create_structure_reader() -> KnowledgeBaseStructureReader:
    return KnowledgeBaseStructureReader()


def _create_query_pipeline() -> KnowledgeBaseQueryPipeline:
    return KnowledgeBaseQueryPipeline(
        retriever=_create_retrieval_service(),
        structure_reader=_create_structure_reader(),
    )


@router.message(Command(VS_COMMAND_NAME))
async def vector_search_handler(message: Message, command: CommandObject) -> None:
    """Run raw vector search in-chat for development and QA checks."""

    if message.from_user is None:
        return

    query = extract_query_text(command)
    if not query:
        await message.bot.send_message(
            chat_id=message.chat.id,
            text=VS_USAGE_TEXT,
            parse_mode=None,
        )
        return

    try:
        retrieval_service = _create_retrieval_service()
        response = retrieval_service.search(
            query=query,
            rewrite_query=False,
        )
        hit_contexts = _resolve_hit_contexts(response.results)
        result_messages = format_search_messages(
            query,
            response,
            hit_contexts=hit_contexts,
        )
    except Exception:
        logger.exception(LOG_EVENT_BOT_VS_SEARCH_FAILED)
        await message.bot.send_message(
            chat_id=message.chat.id,
            text=VS_ERROR_TEXT,
            parse_mode=None,
        )
        return

    await _send_rendered_messages(message, result_messages)


@router.message(Command(QCLASS_COMMAND_NAME))
async def query_classification_handler(message: Message, command: CommandObject) -> None:
    """Temporary debug command: show rules-first query intent classification."""

    await _handle_query_debug(
        message,
        command,
        usage_text=QCLASS_USAGE_TEXT,
        render_fn=lambda query: _render_classification_debug(
            query,
            _create_query_pipeline().classify_query(query),
        ),
    )


@router.message(Command(QPLAN_COMMAND_NAME))
async def query_plan_handler(message: Message, command: CommandObject) -> None:
    """Temporary debug command: show rules-first query plan and scope detection."""

    await _handle_query_debug(
        message,
        command,
        usage_text=QPLAN_USAGE_TEXT,
        render_fn=lambda query: _render_plan_debug(
            query,
            _create_query_pipeline().plan_query(query),
        ),
    )


@router.message(Command(QANSWER_COMMAND_NAME))
async def query_answer_handler(message: Message, command: CommandObject) -> None:
    """Temporary debug command: run the reusable rules-first answer pipeline."""

    await _handle_query_debug(
        message,
        command,
        usage_text=QANSWER_USAGE_TEXT,
        render_fn=lambda query: _render_answer_debug(
            query,
            _create_query_pipeline().answer_query(query, rewrite_query=False),
        ),
    )


async def _handle_query_debug(
    message: Message,
    command: CommandObject,
    *,
    usage_text: str,
    render_fn,
) -> None:
    if message.from_user is None:
        return

    query = extract_query_text(command)
    if not query:
        await message.bot.send_message(
            chat_id=message.chat.id,
            text=usage_text,
            parse_mode=None,
        )
        return

    try:
        rendered_message = render_fn(query)
    except Exception:
        logger.exception(LOG_EVENT_BOT_QDEBUG_FAILED)
        await message.bot.send_message(
            chat_id=message.chat.id,
            text=QDEBUG_ERROR_TEXT,
            parse_mode=None,
        )
        return

    await _send_rendered_messages(message, [rendered_message])


def _resolve_hit_contexts(results) -> list:
    try:
        structure_reader = _create_structure_reader()
        return [structure_reader.resolve_hit_context(hit) for hit in results]
    except Exception:
        logger.debug("kb_debug_hit_context_resolution_failed", exc_info=True)
        return [None for _ in results]


async def _send_rendered_messages(message: Message, rendered_messages: list[str]) -> None:
    for rendered_message in rendered_messages:
        for chunk in split_for_telegram(rendered_message):
            await message.bot.send_message(
                chat_id=message.chat.id,
                text=chunk,
                parse_mode=None,
            )


def _render_classification_debug(query: str, classification: QueryClassification) -> str:
    service_lines = [
        "Service:",
        f"query={query}",
        f"intent={classification.intent}",
        f"confidence={classification.confidence}",
        f"matched_rules={len(classification.matched_rules)}",
    ]
    body_lines = [
        "Matched rules:",
        *[
            f"- {rule.rule_id} (priority={rule.priority} evidence={', '.join(rule.evidence)})"
            for rule in classification.matched_rules
        ],
        "",
        "Rationale:",
        *[f"- {reason}" for reason in classification.rationale],
    ]
    return _render_debug_message(service_lines, "\n".join(body_lines))


def _render_plan_debug(query: str, plan: QueryPlan) -> str:
    service_lines = [
        "Service:",
        f"query={query}",
        f"intent={plan.intent}",
        f"scope={plan.scope_detection.primary_scope}",
        f"strategy={plan.strategy}",
        f"needs_retrieval={plan.needs_retrieval}",
        f"needs_structure={plan.needs_structure}",
    ]
    body_lines = [
        "Intent rules:",
        *[
            f"- {rule.rule_id} (priority={rule.priority} evidence={', '.join(rule.evidence)})"
            for rule in plan.classification.matched_rules
        ],
        "",
        "Scope rules:",
        *[
            f"- {rule.rule_id} (priority={rule.priority} evidence={', '.join(rule.evidence)})"
            for rule in plan.scope_detection.matched_rules
        ],
        "",
        "Plan rationale:",
        *[f"- {reason}" for reason in plan.rationale],
    ]
    return _render_debug_message(service_lines, "\n".join(body_lines))


def _render_answer_debug(query: str, result: QueryAnswerResult) -> str:
    service_lines = [
        "Service:",
        f"query={query}",
        f"intent={result.plan.intent}",
        f"scope={result.plan.scope_detection.primary_scope}",
        f"strategy={result.plan.strategy}",
        f"fallback_used={result.fallback_used}",
        f"source_count={len(result.sources)}",
    ]
    body = render_query_answer(result)
    return _render_debug_message(service_lines, body)


def _render_debug_message(service_lines: list[str], body: str) -> str:
    normalized_body = body.strip() or "(empty)"
    return (
        "\n".join(service_lines)
        + "\n\n--------------------\n\n"
        + normalized_body
    )

