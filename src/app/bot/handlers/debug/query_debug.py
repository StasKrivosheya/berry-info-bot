from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

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
from app.core.constants import DEFAULT_DEBUG_COMMANDS_MODE
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
QROUTE_COMMAND_NAME = "qroute"
QRETRIEVE_COMMAND_NAME = "qretrieve"

QCLASS_USAGE_TEXT = "Usage: /qclass <your question>"
QPLAN_USAGE_TEXT = "Usage: /qplan <your question>"
QANSWER_USAGE_TEXT = "Usage: /qanswer <your question>"
QROUTE_USAGE_TEXT = "Usage: /qroute <your question>"
QRETRIEVE_USAGE_TEXT = "Usage: /qretrieve <your question>"
QDEBUG_ERROR_TEXT = "Query debug tooling is temporarily unavailable. Please try again later."

LOG_EVENT_BOT_VS_SEARCH_FAILED = "bot_vs_search_failed"
LOG_EVENT_BOT_QDEBUG_FAILED = "bot_qdebug_failed"
LOG_EVENT_BOT_DEBUG_ACCESS_BLOCKED = "bot_debug_access_blocked"
QDEBUG_DISABLED_TEXT = "Debug commands are disabled in this environment."
QDEBUG_ADMIN_ONLY_TEXT = "Debug commands are restricted to bot admins."
DebugCommandsMode = Literal["disabled", "admins", "public"]


@lru_cache(maxsize=1)
def _create_retrieval_service() -> KnowledgeBaseRetrievalService:
    return KnowledgeBaseRetrievalService()


@lru_cache(maxsize=1)
def _create_structure_reader() -> KnowledgeBaseStructureReader:
    return KnowledgeBaseStructureReader()


@lru_cache(maxsize=1)
def _create_query_pipeline() -> KnowledgeBaseQueryPipeline:
    return KnowledgeBaseQueryPipeline(
        structure_reader=_create_structure_reader(),
    )


@router.message(Command(VS_COMMAND_NAME))
async def vector_search_handler(
    message: Message,
    command: CommandObject,
    admin_user_ids: set[int] | None = None,
    debug_commands_mode: str | None = None,
) -> None:
    """Run raw vector search in-chat for development and QA checks."""

    if message.from_user is None:
        return

    access_error = _resolve_debug_access_error(
        user_id=message.from_user.id,
        admin_user_ids=admin_user_ids,
        debug_commands_mode=debug_commands_mode,
    )
    if access_error is not None:
        logger.info(
            "%s command=%s user_id=%s mode=%s reason=%s",
            LOG_EVENT_BOT_DEBUG_ACCESS_BLOCKED,
            VS_COMMAND_NAME,
            message.from_user.id,
            _normalize_debug_commands_mode(debug_commands_mode),
            access_error,
        )
        await message.bot.send_message(
            chat_id=message.chat.id,
            text=_debug_access_message(access_error),
            parse_mode=None,
        )
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
        hit_contexts = _resolve_hit_contexts(
            response.results,
            structure_reader=_create_structure_reader(),
        )
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
async def query_classification_handler(
    message: Message,
    command: CommandObject,
    admin_user_ids: set[int] | None = None,
    debug_commands_mode: str | None = None,
) -> None:
    """Temporary debug command: show query classification with policy metadata."""

    await _handle_query_debug(
        message,
        command,
        command_name=QCLASS_COMMAND_NAME,
        admin_user_ids=admin_user_ids,
        debug_commands_mode=debug_commands_mode,
        usage_text=QCLASS_USAGE_TEXT,
        render_fn=lambda query: _render_classification_debug(
            query,
            _create_query_pipeline().classify_query(query),
        ),
    )


@router.message(Command(QPLAN_COMMAND_NAME))
async def query_plan_handler(
    message: Message,
    command: CommandObject,
    admin_user_ids: set[int] | None = None,
    debug_commands_mode: str | None = None,
) -> None:
    """Temporary debug command: show query plan, policy mode, and routing trace."""

    await _handle_query_debug(
        message,
        command,
        command_name=QPLAN_COMMAND_NAME,
        admin_user_ids=admin_user_ids,
        debug_commands_mode=debug_commands_mode,
        usage_text=QPLAN_USAGE_TEXT,
        render_fn=lambda query: _render_plan_debug(
            query,
            _create_query_pipeline().plan_query(query),
        ),
    )


@router.message(Command(QROUTE_COMMAND_NAME))
async def query_route_handler(
    message: Message,
    command: CommandObject,
    admin_user_ids: set[int] | None = None,
    debug_commands_mode: str | None = None,
) -> None:
    """Temporary debug command: render policy routing decisions only."""

    await _handle_query_debug(
        message,
        command,
        command_name=QROUTE_COMMAND_NAME,
        admin_user_ids=admin_user_ids,
        debug_commands_mode=debug_commands_mode,
        usage_text=QROUTE_USAGE_TEXT,
        render_fn=lambda query: _render_policy_debug(
            query,
            _create_query_pipeline().answer_query(query, rewrite_query=False),
        ),
    )


@router.message(Command(QANSWER_COMMAND_NAME))
async def query_answer_handler(
    message: Message,
    command: CommandObject,
    admin_user_ids: set[int] | None = None,
    debug_commands_mode: str | None = None,
) -> None:
    """Temporary debug command: run the reusable rules-first answer pipeline."""

    await _handle_query_debug(
        message,
        command,
        command_name=QANSWER_COMMAND_NAME,
        admin_user_ids=admin_user_ids,
        debug_commands_mode=debug_commands_mode,
        usage_text=QANSWER_USAGE_TEXT,
        render_fn=lambda query: _render_answer_debug(
            query,
            _create_query_pipeline().answer_query(query, rewrite_query=False),
        ),
    )


@router.message(Command(QRETRIEVE_COMMAND_NAME))
async def query_retrieval_handler(
    message: Message,
    command: CommandObject,
    admin_user_ids: set[int] | None = None,
    debug_commands_mode: str | None = None,
) -> None:
    """Temporary debug command: inspect retrieval planning and execution."""

    await _handle_query_debug(
        message,
        command,
        command_name=QRETRIEVE_COMMAND_NAME,
        admin_user_ids=admin_user_ids,
        debug_commands_mode=debug_commands_mode,
        usage_text=QRETRIEVE_USAGE_TEXT,
        render_fn=lambda query: _render_retrieval_debug(
            query,
            _create_query_pipeline().answer_query(query, rewrite_query=False),
        ),
    )


async def _handle_query_debug(
    message: Message,
    command: CommandObject,
    *,
    command_name: str,
    admin_user_ids: set[int] | None,
    debug_commands_mode: str | None,
    usage_text: str,
    render_fn,
) -> None:
    if message.from_user is None:
        return

    access_error = _resolve_debug_access_error(
        user_id=message.from_user.id,
        admin_user_ids=admin_user_ids,
        debug_commands_mode=debug_commands_mode,
    )
    if access_error is not None:
        logger.info(
            "%s command=%s user_id=%s mode=%s reason=%s",
            LOG_EVENT_BOT_DEBUG_ACCESS_BLOCKED,
            command_name,
            message.from_user.id,
            _normalize_debug_commands_mode(debug_commands_mode),
            access_error,
        )
        await message.bot.send_message(
            chat_id=message.chat.id,
            text=_debug_access_message(access_error),
            parse_mode=None,
        )
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


def _resolve_hit_contexts(results, *, structure_reader: KnowledgeBaseStructureReader) -> list:
    try:
        return [structure_reader.resolve_hit_context(hit) for hit in results]
    except Exception:
        logger.debug("kb_debug_hit_context_resolution_failed", exc_info=True)
        return [None for _ in results]


def _resolve_debug_access_error(
    *,
    user_id: int,
    admin_user_ids: set[int] | None,
    debug_commands_mode: str | None,
) -> str | None:
    mode = _normalize_debug_commands_mode(debug_commands_mode)
    if mode == "public":
        return None
    if mode == "disabled":
        return "disabled"

    admin_ids = admin_user_ids or set()
    if user_id in admin_ids:
        return None
    return "admin_only"


def _normalize_debug_commands_mode(value: str | None) -> DebugCommandsMode:
    normalized = str(value or DEFAULT_DEBUG_COMMANDS_MODE).strip().casefold()
    if normalized in {"disabled", "admins", "public"}:
        return normalized  # type: ignore[return-value]
    return DEFAULT_DEBUG_COMMANDS_MODE  # type: ignore[return-value]


def _debug_access_message(access_error: str) -> str:
    if access_error == "disabled":
        return QDEBUG_DISABLED_TEXT
    return QDEBUG_ADMIN_ONLY_TEXT


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
        f"intent_source={classification.source}",
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
        f"intent_source={plan.classification.source}",
        f"scope={plan.scope_detection.primary_scope}",
        f"scope_source={plan.scope_detection.source}",
        f"strategy={plan.strategy}",
        f"strategy_source={plan.strategy_source}",
        f"retrieval_source={plan.retrieval_plan.source}",
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
        "",
        _render_retrieval_plan_body(plan),
        "",
        _render_policy_body(plan),
    ]
    return _render_debug_message(service_lines, "\n".join(line for line in body_lines if line))


def _render_policy_debug(query: str, result: QueryAnswerResult) -> str:
    plan = result.plan
    trace = result.retrieval_trace
    service_lines = [
        "Service:",
        f"query={query}",
        f"mode={plan.policy_trace.mode}",
        f"llm_requested={plan.policy_trace.llm_requested}",
        f"llm_used={plan.policy_trace.llm_used}",
        f"llm_cache_hit={plan.policy_trace.llm_cache_hit}",
        f"llm_escalation_triggered={trace.llm_escalation_triggered if trace else False}",
        f"retry_executed={trace.retry_executed if trace else False}",
    ]
    body_parts = [_render_policy_body(plan), _render_retrieval_trace_body(result)]
    return _render_debug_message(service_lines, "\n\n".join(part for part in body_parts if part))


def _render_answer_debug(query: str, result: QueryAnswerResult) -> str:
    service_lines = [
        "Service:",
        f"query={query}",
        f"intent={result.plan.intent}",
        f"intent_source={result.plan.classification.source}",
        f"scope={result.plan.scope_detection.primary_scope}",
        f"scope_source={result.plan.scope_detection.source}",
        f"strategy={result.plan.strategy}",
        f"strategy_source={result.plan.strategy_source}",
        f"retrieval_source={result.plan.retrieval_plan.source}",
        f"fallback_used={result.fallback_used}",
        f"source_count={len(result.sources)}",
    ]
    body_parts = [
        _render_retrieval_body(result),
        _render_policy_body(result.plan),
        render_query_answer(result),
    ]
    return _render_debug_message(service_lines, "\n\n".join(part for part in body_parts if part))


def _render_retrieval_debug(query: str, result: QueryAnswerResult) -> str:
    merged_result_count = (
        result.retrieval_trace.merged_result_count if result.retrieval_trace else 0
    )
    service_lines = [
        "Service:",
        f"query={query}",
        f"retrieval_source={result.plan.retrieval_plan.source}",
        f"needs_retrieval={result.plan.needs_retrieval}",
        (
            "executed_queries="
            f"{len(result.retrieval_trace.executed_queries) if result.retrieval_trace else 0}"
        ),
        f"merged_result_count={merged_result_count}",
        (
            "retry_executed="
            f"{result.retrieval_trace.retry_executed if result.retrieval_trace else False}"
        ),
    ]
    return _render_debug_message(service_lines, _render_retrieval_body(result))


def _render_policy_body(plan: QueryPlan) -> str:
    trace = plan.policy_trace
    deterministic_retrieval = trace.deterministic_retrieval_plan
    toggle_lines = [
        f"- rules={trace.stage_toggles.rules_enabled}",
        f"- scope={trace.stage_toggles.scope_enabled}",
        f"- planner={trace.stage_toggles.planner_enabled}",
        f"- retrieval={trace.stage_toggles.retrieval_enabled}",
        f"- renderer={trace.stage_toggles.renderer_enabled}",
    ]
    body_lines = [
        "Policy trace:",
        f"- mode={trace.mode}",
        f"- llm_allowed_for={', '.join(trace.llm_allowed_for) or '(none)'}",
        f"- rules_min_confidence={trace.rules_min_confidence}",
        f"- llm_requested={trace.llm_requested}",
        f"- llm_used={trace.llm_used}",
        f"- llm_cache_hit={trace.llm_cache_hit}",
        (
            "- llm_stages_requested="
            f"{', '.join(trace.llm_stages_requested) if trace.llm_stages_requested else '(none)'}"
        ),
        f"- llm_skip_reason={trace.llm_skip_reason or '(none)'}",
        f"- llm_failure_reason={trace.llm_failure_reason or '(none)'}",
        f"- llm_debug_note={trace.llm_debug_note or '(none)'}",
        f"- deterministic_intent={trace.deterministic_classification.intent}",
        (
            "- deterministic_intent_confidence="
            f"{trace.deterministic_classification.confidence}"
        ),
        f"- deterministic_scope={trace.deterministic_scope_detection.primary_scope}",
        (
            "- deterministic_scope_confidence="
            f"{trace.deterministic_scope_detection.confidence}"
        ),
        f"- deterministic_strategy={trace.deterministic_strategy}",
        (
            "- deterministic_retrieval_primary="
            f"{_deterministic_retrieval_primary(deterministic_retrieval)}"
        ),
        f"- final_intent_source={trace.final_intent_source}",
        f"- final_scope_source={trace.final_scope_source}",
        f"- final_strategy_source={trace.final_strategy_source}",
        f"- final_retrieval_source={trace.final_retrieval_source}",
        "",
        "Stage toggles:",
        *toggle_lines,
    ]
    return "\n".join(body_lines)


def _render_retrieval_body(result: QueryAnswerResult) -> str:
    body_parts = [
        _render_retrieval_plan_body(result.plan),
    ]
    if result.retrieval_trace is not None:
        body_parts.append(_render_retrieval_trace_body(result))
    return "\n\n".join(part for part in body_parts if part)


def _render_retrieval_plan_body(plan: QueryPlan) -> str:
    retrieval_plan = plan.retrieval_plan
    alternate_queries = ", ".join(retrieval_plan.alternate_queries) or "(none)"
    keywords = ", ".join(retrieval_plan.keywords) or "(none)"
    rationale = "\n".join(f"- {note}" for note in retrieval_plan.rationale) or "- (none)"
    return "\n".join(
        (
            "Retrieval plan:",
            f"- source={retrieval_plan.source}",
            f"- primary_query={retrieval_plan.primary_query}",
            f"- alternate_queries={alternate_queries}",
            f"- keywords={keywords}",
            f"- confidence={retrieval_plan.confidence}",
            f"- debug_note={retrieval_plan.debug_note or '(none)'}",
            "Rationale:",
            rationale,
        )
    )


def _render_retrieval_trace_body(result: QueryAnswerResult) -> str:
    trace = result.retrieval_trace
    if trace is None:
        return ""
    initial_top_score = (
        str(trace.initial_top_score) if trace.initial_top_score is not None else "(none)"
    )
    retry_top_score = str(trace.retry_top_score) if trace.retry_top_score is not None else "(none)"
    renderer_trusted_top_hit = (
        str(trace.renderer_trusted_top_hit)
        if trace.renderer_trusted_top_hit is not None
        else "(none)"
    )
    top_score = (
        str(result.search_response.top_score)
        if result.search_response is not None and result.search_response.top_score is not None
        else "(none)"
    )
    initial_planned_queries = ", ".join(trace.initial_planned_queries) or "(none)"
    initial_executed_queries = ", ".join(trace.initial_executed_queries) or "(none)"
    planned_queries = ", ".join(trace.planned_queries) or "(none)"
    executed_queries = ", ".join(trace.executed_queries) or "(none)"
    return "\n".join(
        (
            "Retrieval execution:",
            f"- initial_planned_queries={initial_planned_queries}",
            f"- initial_executed_queries={initial_executed_queries}",
            f"- initial_result_count={trace.initial_result_count}",
            f"- initial_top_score={initial_top_score}",
            f"- initial_stop_reason={trace.initial_stop_reason or '(none)'}",
            f"- llm_escalation_triggered={trace.llm_escalation_triggered}",
            f"- llm_escalation_reason={trace.llm_escalation_reason or '(none)'}",
            f"- retry_executed={trace.retry_executed}",
            f"- final_planned_queries={planned_queries}",
            f"- final_executed_queries={executed_queries}",
            f"- planned_queries={planned_queries}",
            f"- executed_queries={executed_queries}",
            f"- retry_result_count={trace.retry_result_count}",
            f"- retry_top_score={retry_top_score}",
            f"- merged_raw_hit_count={trace.merged_raw_hit_count}",
            f"- merged_result_count={trace.merged_result_count}",
            f"- top_score={top_score}",
            f"- stop_reason={trace.stop_reason or '(none)'}",
            f"- renderer_trusted_top_hit={renderer_trusted_top_hit}",
            f"- renderer_note={trace.renderer_note or '(none)'}",
        )
    )


def _deterministic_retrieval_primary(deterministic_retrieval) -> str:
    if deterministic_retrieval is None:
        return "(none)"
    return deterministic_retrieval.primary_query


def _render_debug_message(service_lines: list[str], body: str) -> str:
    normalized_body = body.strip() or "(empty)"
    return "\n".join(service_lines) + "\n\n--------------------\n\n" + normalized_body
