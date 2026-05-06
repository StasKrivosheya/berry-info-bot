from __future__ import annotations

from pathlib import Path

from app.services.knowledge_base.query_router import (
    SERVICE_FALLBACK_TEXT,
    QueryContextKey,
    QueryContextStore,
    QueryRoute,
    route_free_text_message,
)

EVAL_CASES_PATH = Path(__file__).parent / "evals" / "qa_cases.yaml"


class StaticRouter:
    def __init__(self, route: QueryRoute) -> None:
        self._route = route

    def route(self, message: str, *, context=None) -> QueryRoute:
        del message, context
        return self._route


def test_eval_cases_exercise_final_routing_contract() -> None:
    for case in _load_eval_cases(EVAL_CASES_PATH):
        route = _route_from_case(case)
        result = route_free_text_message(
            router=StaticRouter(route),
            context_store=QueryContextStore(ttl_seconds=900, monotonic=lambda: 1.0),
            context_key=QueryContextKey(chat_id=1, user_id=1),
            message=str(case["query"]),
        )

        assert result.route is not None, case["id"]
        assert result.should_search is case["expected_should_search"], case["id"]
        assert (result.route.topic_hint or "") == case["expected_topic_hint"], case["id"]
        assert result.route.direction_hints == _csv(
            case.get("expected_direction_hints"),
        ), case["id"]

        expected_response = case["expected_response"]
        if expected_response == "clarify":
            assert "уточніть напрямок" in result.response_text.casefold(), case["id"]
        elif expected_response == "service":
            assert result.response_text == SERVICE_FALLBACK_TEXT, case["id"]


def _route_from_case(case: dict[str, object]) -> QueryRoute:
    route = str(case["route"])
    query = str(case["query"])
    if route in {"kb_query", "follow_up"}:
        return QueryRoute(
            route=route,
            original_message=query,
            canonical_question_uk=query,
            vector_query_uk=query,
            lexical_keywords=[query.split()[0]],
            lexical_phrases=[query],
            topic_hint=_optional(case.get("topic_hint")),
            direction_hints=_csv(case.get("direction_hints")),
            confidence=0.9,
        )
    return QueryRoute(
        route=route,
        original_message=query,
        topic_hint=_optional(case.get("topic_hint")),
        direction_hints=_csv(case.get("direction_hints")),
        confidence=0.9,
    )


def _load_eval_cases(path: Path) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped == "cases:":
            continue
        if stripped.startswith("- id: "):
            current = {"id": _scalar(stripped.removeprefix("- id: "))}
            cases.append(current)
            continue
        if current is None:
            continue
        key, _, value = stripped.partition(": ")
        if key and value:
            current[key] = _scalar(value)

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


def _optional(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _csv(value: object) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]
