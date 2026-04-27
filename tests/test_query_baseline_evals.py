from __future__ import annotations

from pathlib import Path

from app.services.knowledge_base.query.config import KnowledgeBaseQuerySettings
from app.services.knowledge_base.query.pipeline import KnowledgeBaseQueryPipeline
from app.services.knowledge_base.query.types import StructuredDocument
from app.services.knowledge_base.types_openai import NO_RELEVANT_INFO_FALLBACK, SearchResponse

EVAL_CASES_PATH = Path(__file__).parent / "evals" / "qa_cases.yaml"


class EmptyRetriever:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> SearchResponse:
        self.calls.append(kwargs)
        return SearchResponse(
            results=[],
            top_score=None,
            used_threshold=0.7,
            fallback_triggered=True,
            fallback_message=NO_RELEVANT_INFO_FALLBACK,
        )


class EmptyStructureReader:
    manifest_path = Path("tests/evals/empty-manifest.json")

    def documents_for_scopes(self, scopes: tuple[str, ...]) -> tuple[StructuredDocument, ...]:
        return ()

    def load_documents(self) -> tuple[StructuredDocument, ...]:
        return ()

    def resolve_vector_hit_context(self, hit: object) -> None:
        return None


def _disabled_query_settings() -> KnowledgeBaseQuerySettings:
    return KnowledgeBaseQuerySettings(
        _env_file=None,
        kb_query_llm_mode="disabled",
        kb_query_llm_allowed_for=("classifier", "scope", "planner", "retrieval"),
        kb_query_rules_min_confidence=0.85,
        kb_query_enable_stage_rules=True,
        kb_query_enable_stage_scope=True,
        kb_query_enable_stage_planner=True,
        kb_query_enable_stage_retrieval=True,
        kb_query_enable_stage_renderer=True,
        kb_query_llm_model=None,
        kb_query_llm_timeout_seconds=10,
        kb_query_llm_cache_size=32,
        kb_query_llm_max_retrieval_variants=1,
        openai_api_key=None,
    )


def _load_eval_cases(path: Path) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    expected: dict[str, object] | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped == "cases:":
            continue
        if stripped.startswith("- id: "):
            current = {"id": _scalar(stripped.removeprefix("- id: "))}
            expected = None
            cases.append(current)
            continue
        if current is None:
            continue
        if stripped == "expected:":
            expected = {}
            current["expected"] = expected
            continue

        key, _, value = stripped.partition(": ")
        if not key or not value:
            continue
        target = expected if expected is not None else current
        target[key] = _scalar(value)

    return cases


def _scalar(value: str) -> object:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    if value == "true":
        return True
    if value == "false":
        return False
    return value


def test_eval_cases_capture_current_multilingual_route_baseline() -> None:
    pipeline = KnowledgeBaseQueryPipeline(policy_settings=_disabled_query_settings())

    for case in _load_eval_cases(EVAL_CASES_PATH):
        expected = case["expected"]
        assert isinstance(expected, dict)

        plan = pipeline.plan_query(str(case["query"]))

        assert plan.intent == expected["intent"], case["id"]
        assert plan.scope_detection.primary_scope == expected["scope"], case["id"]
        assert plan.strategy == expected["strategy"], case["id"]
        assert plan.needs_retrieval is expected["needs_retrieval"], case["id"]


def test_pipeline_returns_evidence_only_fallback_when_retrieval_has_no_hits() -> None:
    retriever = EmptyRetriever()
    pipeline = KnowledgeBaseQueryPipeline(
        retriever=retriever,
        structure_reader=EmptyStructureReader(),
        policy_settings=_disabled_query_settings(),
    )

    inspection = pipeline.inspect_query("What programs do you offer?")

    assert retriever.calls == [
        {
            "query": "What programs do you offer?",
            "max_num_results": None,
            "rewrite_query": False,
            "score_threshold": None,
            "category": None,
            "logical_id": None,
            "attribute_filters": None,
        }
    ]
    assert inspection.answer_result.state == "fallback"
    assert inspection.answer_result.answer_text == NO_RELEVANT_INFO_FALLBACK
    assert inspection.answer_result.source_section_ids == ()
    assert inspection.evidence_packet is not None
    assert inspection.evidence_packet.items == ()
