from __future__ import annotations

from app.services.knowledge_base.query.types import QueryAnswerResult, QueryRetrievalExecutionTrace


def with_retrieval_trace(
    result: QueryAnswerResult,
    retrieval_trace: QueryRetrievalExecutionTrace | None,
    *,
    trusted_top_hit: bool | None = None,
    note: str | None = None,
) -> QueryAnswerResult:
    trace = retrieval_trace
    if trace is not None:
        trace = QueryRetrievalExecutionTrace(
            initial_planned_queries=trace.initial_planned_queries,
            initial_executed_queries=trace.initial_executed_queries,
            initial_result_count=trace.initial_result_count,
            initial_top_score=trace.initial_top_score,
            initial_stop_reason=trace.initial_stop_reason,
            llm_escalation_triggered=trace.llm_escalation_triggered,
            llm_escalation_reason=trace.llm_escalation_reason,
            retry_executed=trace.retry_executed,
            planned_queries=trace.planned_queries,
            executed_queries=trace.executed_queries,
            retry_result_count=trace.retry_result_count,
            retry_top_score=trace.retry_top_score,
            merged_raw_hit_count=trace.merged_raw_hit_count,
            merged_result_count=trace.merged_result_count,
            stop_reason=trace.stop_reason,
            renderer_trusted_top_hit=(
                trusted_top_hit
                if trusted_top_hit is not None
                else trace.renderer_trusted_top_hit
            ),
            renderer_note=note if note is not None else trace.renderer_note,
        )
    return QueryAnswerResult(
        plan=result.plan,
        blocks=result.blocks,
        summary=result.summary,
        sources=result.sources,
        search_response=result.search_response,
        fallback_used=result.fallback_used,
        retrieval_trace=trace,
    )
