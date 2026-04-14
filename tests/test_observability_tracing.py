from __future__ import annotations

import asyncio
import io
import json
import logging
from pathlib import Path
from types import SimpleNamespace

from app.bot.middlewares.tracing import TraceContextMiddleware
from app.core.logging import JsonLogFormatter
from app.observability import (
    LOG_EVENT_TRACE_REQUEST_FINISHED,
    LOG_EVENT_TRACE_REQUEST_STARTED,
    LOG_EVENT_TRACE_SPAN,
    get_trace_id,
    reset_trace_id,
    set_trace_id,
)
from app.services.knowledge_base.query.pipeline import KnowledgeBaseQueryPipeline
from app.services.knowledge_base.query.types import (
    QueryClassification,
    QueryPlan,
    QueryPolicyTrace,
    QueryRetrievalPlan,
    QueryScopeDetection,
    QueryStageToggles,
    SearchHitDebugContext,
    StructuredDocument,
    StructuredSection,
)
from app.services.knowledge_base.types_openai import SearchHit, SearchResponse


class FakeTraceAwareHandler:
    def __init__(self) -> None:
        self.observed_trace_id: str | None = None

    async def __call__(self, event, data: dict[str, object]) -> str:
        del event
        self.observed_trace_id = str(data["trace_id"])
        assert get_trace_id() == self.observed_trace_id
        return "handled"


class StaticQueryPolicy:
    def __init__(self, plan: QueryPlan) -> None:
        self._plan = plan
        self.settings = SimpleNamespace(
            kb_query_llm_mode="forced",
            kb_query_llm_max_retrieval_variants=1,
        )

    def resolve_query_plan(
        self,
        query: str,
        *,
        llm_mode_override=None,
    ) -> QueryPlan:
        del query, llm_mode_override
        return self._plan


class SuccessfulRetriever:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> SearchResponse:
        self.calls.append(kwargs)
        return SearchResponse(
            results=[
                SearchHit(
                    file_id="file-1",
                    filename="berry.md",
                    score=0.93,
                    attributes={"logical_id": "berry-faq"},
                    text="Open daily from 10:00 to 19:00",
                )
            ],
            top_score=0.93,
            used_threshold=0.7,
            fallback_triggered=False,
        )


class FakeStructureReader:
    manifest_path = Path("data/knowledge_base/processed/manifest.json")

    def __init__(self) -> None:
        self._documents = (
            StructuredDocument(
                logical_id="berry-faq",
                title="Berry FAQ",
                category="faq",
                source_file="berry.md",
                markdown_path=Path("data/knowledge_base/processed/markdown/berry.md"),
                scopes=("general",),
                sections=(
                    StructuredSection(
                        heading="Hours",
                        level=2,
                        heading_path=("Berry FAQ", "Hours"),
                        body="Open daily from 10:00 to 19:00",
                    ),
                ),
            ),
        )

    def load_documents(self) -> tuple[StructuredDocument, ...]:
        return self._documents

    def documents_for_scopes(self, scopes) -> tuple[StructuredDocument, ...]:
        del scopes
        return self._documents

    def resolve_hit_context(self, hit: SearchHit) -> SearchHitDebugContext:
        del hit
        return SearchHitDebugContext(
            logical_id="berry-faq",
            source_file="berry.md",
            document_title="Berry FAQ",
            heading_path=("Berry FAQ", "Hours"),
        )


def test_trace_context_middleware_reuses_x_request_id() -> None:
    middleware = TraceContextMiddleware()
    handler = FakeTraceAwareHandler()

    result = asyncio.run(
        middleware(
            handler,
            SimpleNamespace(),
            {"headers": {"X-Request-Id": "req-123"}},
        )
    )

    assert result == "handled"
    assert handler.observed_trace_id == "req-123"
    assert get_trace_id() is None


def test_trace_context_middleware_logs_user_and_chat_metadata() -> None:
    middleware = TraceContextMiddleware()
    handler = FakeTraceAwareHandler()
    stream = io.StringIO()
    log_handler = logging.StreamHandler(stream)
    log_handler.setFormatter(JsonLogFormatter())
    middleware_logger = logging.getLogger("app.bot.middlewares.tracing")
    previous_level = middleware_logger.level
    previous_propagate = middleware_logger.propagate
    middleware_logger.handlers.clear()
    middleware_logger.addHandler(log_handler)
    middleware_logger.setLevel(logging.INFO)
    middleware_logger.propagate = False

    event = SimpleNamespace(
        update_id=777,
        from_user=SimpleNamespace(id=1001),
        chat=SimpleNamespace(id=2002),
    )
    try:
        result = asyncio.run(middleware(handler, event, {}))
    finally:
        middleware_logger.removeHandler(log_handler)
        middleware_logger.setLevel(previous_level)
        middleware_logger.propagate = previous_propagate

    assert result == "handled"
    log_lines = [
        json.loads(line)
        for line in stream.getvalue().splitlines()
        if line.strip()
    ]
    request_logs = [
        line
        for line in log_lines
        if line.get("event") in {LOG_EVENT_TRACE_REQUEST_STARTED, LOG_EVENT_TRACE_REQUEST_FINISHED}
    ]

    assert len(request_logs) == 2
    assert all(line["meta"]["user_id"] == 1001 for line in request_logs)
    assert all(line["meta"]["chat_id"] == 2002 for line in request_logs)
    assert all(line["meta"]["update_id"] == 777 for line in request_logs)


def test_pipeline_smoke_logs_trace_id_and_stage_spans() -> None:
    query = "What are the opening hours?"
    classification = QueryClassification(
        intent="detail",
        confidence=0.98,
        rationale=("User asks for a specific operational detail.",),
    )
    scope = QueryScopeDetection(
        primary_scope="general",
        scopes=("general",),
        confidence=0.9,
        rationale=("The stub document is globally relevant.",),
    )
    retrieval_plan = QueryRetrievalPlan(
        primary_query=query,
        confidence=0.92,
        source="rules",
        rationale=("Use the raw query for deterministic retrieval.",),
    )
    stage_toggles = QueryStageToggles()
    plan = QueryPlan(
        classification=classification,
        scope_detection=scope,
        strategy="detail_retrieval",
        retrieval_plan=retrieval_plan,
        needs_retrieval=True,
        needs_structure=True,
        rationale=("Detail intent selects retrieval-backed section answering.",),
        strategy_source="rules",
        policy_trace=QueryPolicyTrace(
            mode="forced",
            stage_toggles=stage_toggles,
            rules_min_confidence=0.85,
            deterministic_classification=classification,
            deterministic_scope_detection=scope,
            deterministic_strategy="detail_retrieval",
            deterministic_retrieval_plan=retrieval_plan,
            final_intent_source="rules",
            final_scope_source="rules",
            final_strategy_source="rules",
            final_retrieval_source="rules",
        ),
    )

    retriever = SuccessfulRetriever()
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=FakeStructureReader(),
        query_policy=StaticQueryPolicy(plan),
    )

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG)

    token = set_trace_id("trace-smoke-test")
    try:
        result = pipeline.answer_query(query, rewrite_query=False)
    finally:
        reset_trace_id(token)
        root_logger.removeHandler(handler)
        root_logger.setLevel(previous_level)

    assert retriever.calls == [
        {
            "query": query,
            "max_num_results": None,
            "rewrite_query": False,
            "score_threshold": None,
            "category": None,
            "logical_id": None,
            "attribute_filters": None,
        }
    ]
    assert result.summary is not None

    log_lines = [
        json.loads(line)
        for line in stream.getvalue().splitlines()
        if line.strip()
    ]
    span_logs = [
        line
        for line in log_lines
        if line.get("event") == LOG_EVENT_TRACE_SPAN
    ]

    assert len(span_logs) >= 3
    assert {line["trace_id"] for line in span_logs} == {"trace-smoke-test"}
    assert {"plan", "retrieval", "render"}.issubset({line["stage"] for line in span_logs})
    assert all(line["status"] in {"ok", "error", "skipped"} for line in span_logs)
    assert all(line["duration_ms"] >= 0 for line in span_logs)
