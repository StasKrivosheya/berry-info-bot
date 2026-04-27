from __future__ import annotations

from types import SimpleNamespace

from app.services.knowledge_base.query_router import (
    FOLLOW_UP_CLARIFICATION_TEXT,
    QUERY_ROUTER_PROMPT,
    SERVICE_FALLBACK_TEXT,
    OpenAIQueryRouter,
    QueryContextKey,
    QueryContextStore,
    QueryRoute,
    build_query_router_input,
    route_free_text_message,
)

# ruff: noqa: RUF001


class StaticRouter:
    def __init__(self, *routes: QueryRoute, error: Exception | None = None) -> None:
        self._routes = list(routes)
        self._error = error
        self.calls: list[dict[str, object]] = []

    def route(self, message: str, *, context=None) -> QueryRoute:
        self.calls.append({"message": message, "context": context})
        if self._error is not None:
            raise self._error
        if not self._routes:
            raise RuntimeError("No route configured.")
        return self._routes.pop(0)


class FakeResponses:
    def __init__(self, parsed: QueryRoute | None) -> None:
        self.parsed = parsed
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.parsed)


class FakeOpenAIClient:
    def __init__(self, parsed: QueryRoute | None) -> None:
        self.responses = FakeResponses(parsed)


def _key() -> QueryContextKey:
    return QueryContextKey(chat_id=100, user_id=200)


def _store() -> QueryContextStore:
    return QueryContextStore(ttl_seconds=900, monotonic=lambda: 1.0)


def _route(
    route: str,
    *,
    original_message: str = "Привіт",
    canonical_question_uk: str | None = None,
    vector_query_uk: str | None = None,
    lexical_keywords: list[str] | None = None,
    lexical_phrases: list[str] | None = None,
    use_context: bool = False,
    confidence: float = 0.9,
) -> QueryRoute:
    return QueryRoute(
        route=route,
        original_message=original_message,
        canonical_question_uk=canonical_question_uk,
        vector_query_uk=vector_query_uk,
        lexical_keywords=lexical_keywords or [],
        lexical_phrases=lexical_phrases or [],
        use_context=use_context,
        confidence=confidence,
    )


def test_greeting_returns_service_text_and_no_search() -> None:
    result = route_free_text_message(
        router=StaticRouter(_route("greeting")),
        context_store=_store(),
        context_key=_key(),
        message="Привіт",
    )

    assert result.route is not None
    assert result.route.route == "greeting"
    assert result.response_text == SERVICE_FALLBACK_TEXT
    assert result.should_search is False


def test_smalltalk_returns_service_text_and_no_search() -> None:
    result = route_free_text_message(
        router=StaticRouter(_route("smalltalk", original_message="Як справи?")),
        context_store=_store(),
        context_key=_key(),
        message="Як справи?",
    )

    assert result.route is not None
    assert result.route.route == "smalltalk"
    assert result.response_text == SERVICE_FALLBACK_TEXT
    assert result.should_search is False


def test_ukrainian_kb_question_produces_searchable_route() -> None:
    route = _route(
        "kb_query",
        original_message="Які у вас є програми?",
        canonical_question_uk="Які програми доступні в Berry Land?",
        vector_query_uk="організовані програми Berry Land",
        lexical_keywords=["програми", "Berry Land"],
        lexical_phrases=["організовані програми"],
    )

    result = route_free_text_message(
        router=StaticRouter(route),
        context_store=_store(),
        context_key=_key(),
        message="Які у вас є програми?",
    )

    assert result.route == route
    assert result.should_search is True
    assert result.route.canonical_question_uk == "Які програми доступні в Berry Land?"
    assert result.route.vector_query_uk == "організовані програми Berry Land"


def test_russian_and_english_questions_return_ukrainian_canonical_queries() -> None:
    cases = (
        (
            "Какие программы есть?",
            "Які програми доступні в Berry Land?",
            "організовані програми Berry Land",
        ),
        (
            "What is the park schedule?",
            "Який графік роботи парку Berry Land?",
            "графік роботи парку Berry Land",
        ),
    )

    for message, canonical, vector_query in cases:
        parsed = _route(
            "kb_query",
            original_message=message,
            canonical_question_uk=canonical,
            vector_query_uk=vector_query,
            lexical_keywords=["Berry Land"],
            lexical_phrases=[vector_query],
        )
        client = FakeOpenAIClient(parsed)
        router = OpenAIQueryRouter(
            api_key="test-key",
            model="test-model",
            timeout_seconds=7,
            client=client,
        )

        route = router.route(message)

        assert route.original_message == message
        assert route.reply_language == "uk"
        assert route.canonical_question_uk == canonical
        assert route.vector_query_uk == vector_query
        call = client.responses.calls[0]
        assert call["text_format"] is QueryRoute
        assert call["instructions"] == QUERY_ROUTER_PROMPT
        assert call["reasoning"] == {"effort": "none"}
        assert "Previous context: none" in str(call["input"])


def test_short_follow_up_uses_previous_context_when_available() -> None:
    store = _store()
    context_key = _key()
    first_route = _route(
        "kb_query",
        original_message="Які у вас є програми?",
        canonical_question_uk="Які програми доступні в Berry Land?",
        vector_query_uk="організовані програми Berry Land",
        lexical_keywords=["програми"],
        lexical_phrases=["організовані програми"],
    )
    follow_up_route = _route(
        "follow_up",
        original_message="А скільки коштує?",
        canonical_question_uk="Скільки коштують програми Berry Land?",
        vector_query_uk="вартість організованих програм Berry Land",
        lexical_keywords=["вартість", "програми"],
        lexical_phrases=["вартість програм"],
        use_context=True,
    )
    router = StaticRouter(first_route, follow_up_route)

    first = route_free_text_message(
        router=router,
        context_store=store,
        context_key=context_key,
        message="Які у вас є програми?",
    )
    second = route_free_text_message(
        router=router,
        context_store=store,
        context_key=context_key,
        message="А скільки коштує?",
    )

    assert first.should_search is True
    assert second.route == follow_up_route
    assert second.should_search is True
    assert second.used_context is True
    assert router.calls[0]["context"] is None
    assert router.calls[1]["context"] is not None


def test_follow_up_without_context_asks_for_clarification() -> None:
    result = route_free_text_message(
        router=StaticRouter(_route("follow_up", original_message="А ціна?", confidence=0.55)),
        context_store=_store(),
        context_key=_key(),
        message="А ціна?",
    )

    assert result.route is not None
    assert result.route.route == "follow_up"
    assert result.response_text == FOLLOW_UP_CLARIFICATION_TEXT
    assert result.should_search is False


def test_malformed_llm_output_fails_safely() -> None:
    router = OpenAIQueryRouter(
        api_key="test-key",
        model="test-model",
        timeout_seconds=7,
        client=FakeOpenAIClient(parsed=None),
    )

    result = route_free_text_message(
        router=router,
        context_store=_store(),
        context_key=_key(),
        message="Які програми є?",
    )

    assert result.route is None
    assert result.response_text == SERVICE_FALLBACK_TEXT
    assert result.should_search is False


def test_router_input_includes_previous_context() -> None:
    route = _route(
        "kb_query",
        canonical_question_uk="Які програми доступні в Berry Land?",
        vector_query_uk="організовані програми Berry Land",
        lexical_keywords=["програми"],
        lexical_phrases=["організовані програми"],
    )
    store = _store()
    store.save(_key(), route)

    prompt_input = build_query_router_input("А ціна?", context=store.get(_key()))

    assert "User message: А ціна?" in prompt_input
    assert "canonical_question_uk: Які програми доступні в Berry Land?" in prompt_input
    assert "vector_query_uk: організовані програми Berry Land" in prompt_input
