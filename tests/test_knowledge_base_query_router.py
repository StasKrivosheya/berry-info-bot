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

MAX_CONTEXT_TEST_TURNS = 5


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
    topic_hint: str | None = None,
    direction_hints: list[str] | None = None,
    query_specificity: str = "concrete",
    question_scope: str = "unknown",
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
        topic_hint=topic_hint,
        direction_hints=direction_hints or [],
        query_specificity=query_specificity,
        question_scope=question_scope,
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


def test_ukrainian_program_question_without_direction_searches_broadly() -> None:
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

    assert result.route is not None
    assert result.should_search is True
    assert result.route.canonical_question_uk == "Які програми доступні в Berry Land?"
    assert result.route.vector_query_uk == "організовані програми Berry Land"
    assert result.route.topic_hint == "programs"
    assert result.route.direction_hints == []
    assert result.route.question_scope == "broad"


def test_direction_sensitive_topic_without_direction_asks_for_clarification() -> None:
    route = _route(
        "kb_query",
        original_message="Скільки коштують квитки?",
        canonical_question_uk="Яка вартість квитків у Berry Land?",
        vector_query_uk="вартість квитків Berry Land",
        lexical_keywords=["квитки", "вартість"],
        lexical_phrases=["вартість квитків"],
        topic_hint="tickets",
    )

    result = route_free_text_message(
        router=StaticRouter(route),
        context_store=_store(),
        context_key=_key(),
        message="Скільки коштують квитки?",
    )

    assert result.route is not None
    assert result.route.topic_hint == "tickets"
    assert result.route.direction_hints == []
    assert result.should_search is False
    assert "ОП" in result.response_text
    assert "СВ" in result.response_text


def test_concrete_unknown_topic_searches_broadly() -> None:
    route = _route(
        "kb_query",
        original_message="какие животные есть в парке?",
        canonical_question_uk="Які тварини є в парку Berry Land?",
        vector_query_uk="тварини парк Berry Land",
        lexical_keywords=["тварини", "парк"],
        lexical_phrases=["тварини в парку"],
        query_specificity="concrete",
    )

    result = route_free_text_message(
        router=StaticRouter(route),
        context_store=_store(),
        context_key=_key(),
        message="какие животные есть в парке?",
    )

    assert result.route is not None
    assert result.should_search is True
    assert result.clarification_kind is None
    assert result.route.topic_hint is None
    assert result.route.direction_hints == []
    assert result.route.question_scope == "broad"


def test_services_and_rules_without_direction_search_broadly() -> None:
    cases = (
        ("додаткові послуги", "services", "додаткові послуги Berry Land"),
        ("які правила в парку?", "rules", "правила Berry Land"),
    )

    for message, topic_hint, vector_query in cases:
        route = _route(
            "kb_query",
            original_message=message,
            canonical_question_uk=message,
            vector_query_uk=vector_query,
            lexical_keywords=[topic_hint],
            lexical_phrases=[vector_query],
            topic_hint=topic_hint,
        )

        result = route_free_text_message(
            router=StaticRouter(route),
            context_store=_store(),
            context_key=_key(),
            message=message,
        )

        assert result.route is not None
        assert result.should_search is True, topic_hint
        assert result.clarification_kind is None, topic_hint
        assert result.route.direction_hints == [], topic_hint


def test_controlled_direction_allows_search_for_sensitive_topic() -> None:
    route = _route(
        "kb_query",
        original_message="Скільки коштують квитки на СВ?",
        canonical_question_uk="Яка вартість квитків для сімейного відпочинку?",
        vector_query_uk="вартість квитків сімейний відпочинок Berry Land",
        lexical_keywords=["квитки", "вартість", "сімейний відпочинок"],
        lexical_phrases=["вартість квитків"],
        topic_hint="tickets",
        direction_hints=["sv"],
    )

    result = route_free_text_message(
        router=StaticRouter(route),
        context_store=_store(),
        context_key=_key(),
        message="Скільки коштують квитки на СВ?",
    )

    assert result.route is not None
    assert result.route.direction_hints == ["sv"]
    assert result.should_search is True


def test_likely_kb_query_rescues_unsupported_route() -> None:
    result = route_free_text_message(
        router=StaticRouter(
            _route(
                "unsupported",
                original_message="какие животные есть в парке?",
                confidence=0.4,
            ),
        ),
        context_store=_store(),
        context_key=_key(),
        message="какие животные есть в парке?",
    )

    assert result.route is not None
    assert result.route.route == "kb_query"
    assert result.should_search is True
    assert result.route.query_specificity == "concrete"
    assert result.route.question_scope == "broad"
    assert result.route.clarification_reason == "deterministic_kb_rescue"


def test_pending_direction_clarification_accepts_short_direction_reply() -> None:
    store = _store()
    context_key = _key()
    first_route = _route(
        "kb_query",
        original_message="Скільки коштують квитки?",
        canonical_question_uk="Яка вартість квитків у Berry Land?",
        vector_query_uk="вартість квитків Berry Land",
        lexical_keywords=["квитки", "вартість"],
        lexical_phrases=["вартість квитків"],
        topic_hint="tickets",
    )
    router = StaticRouter(first_route)

    first = route_free_text_message(
        router=router,
        context_store=store,
        context_key=context_key,
        message="Скільки коштують квитки?",
    )
    second = route_free_text_message(
        router=router,
        context_store=store,
        context_key=context_key,
        message="св",
    )

    assert first.should_search is False
    assert first.clarification_kind == "direction"
    assert second.route is not None
    assert second.should_search is True
    assert second.used_context is True
    assert second.route.route == "follow_up"
    assert second.route.topic_hint == "tickets"
    assert second.route.direction_hints == ["sv"]
    assert len(router.calls) == 1


def test_pending_direction_clarification_accepts_multiple_directions() -> None:
    store = _store()
    context_key = _key()
    first_route = _route(
        "kb_query",
        original_message="Скільки коштують квитки?",
        canonical_question_uk="Яка вартість квитків у Berry Land?",
        vector_query_uk="вартість квитків Berry Land",
        lexical_keywords=["квитки", "вартість"],
        lexical_phrases=["вартість квитків"],
        topic_hint="tickets",
    )
    router = StaticRouter(first_route)

    route_free_text_message(
        router=router,
        context_store=store,
        context_key=context_key,
        message="Скільки коштують квитки?",
    )
    second = route_free_text_message(
        router=router,
        context_store=store,
        context_key=context_key,
        message="і св і оп",
    )

    assert second.route is not None
    assert second.should_search is True
    assert second.route.direction_hints == ["op", "sv"]
    assert "ОП" in second.route.vector_query_uk
    assert "СВ" in second.route.vector_query_uk
    assert len(router.calls) == 1


def test_pending_direction_clarification_lets_new_kb_question_route_normally() -> None:
    store = _store()
    context_key = _key()
    first_route = _route(
        "kb_query",
        original_message="Скільки коштують квитки?",
        canonical_question_uk="Яка вартість квитків у Berry Land?",
        vector_query_uk="вартість квитків Berry Land",
        lexical_keywords=["квитки", "вартість"],
        lexical_phrases=["вартість квитків"],
        topic_hint="tickets",
    )
    second_route = _route(
        "kb_query",
        original_message="додаткові послуги",
        canonical_question_uk="Які додаткові послуги є в Berry Land?",
        vector_query_uk="додаткові послуги Berry Land",
        lexical_keywords=["послуги"],
        lexical_phrases=["додаткові послуги"],
        topic_hint="services",
    )
    router = StaticRouter(first_route, second_route)

    first = route_free_text_message(
        router=router,
        context_store=store,
        context_key=context_key,
        message="Скільки коштують квитки?",
    )
    second = route_free_text_message(
        router=router,
        context_store=store,
        context_key=context_key,
        message="додаткові послуги",
    )

    assert first.clarification_kind == "direction"
    assert second.route is not None
    assert second.should_search is True
    assert second.used_context is False
    assert second.route.route == "kb_query"
    assert second.route.topic_hint == "services"
    assert second.route.direction_hints == []
    assert len(router.calls) == 2


def test_program_topic_without_direction_searches_broadly() -> None:
    route = _route(
        "kb_query",
        original_message="Які є види програм?",
        canonical_question_uk="Які є види програм у Berry Land?",
        vector_query_uk="види організованих програм Berry Land",
        lexical_keywords=["програми"],
        lexical_phrases=["види програм"],
        topic_hint="programs",
    )

    result = route_free_text_message(
        router=StaticRouter(route),
        context_store=_store(),
        context_key=_key(),
        message="Які є види програм?",
    )

    assert result.route is not None
    assert result.route.direction_hints == []
    assert result.should_search is True
    assert result.route.question_scope == "broad"


def test_program_topic_with_direction_allows_search() -> None:
    route = _route(
        "kb_query",
        original_message="РЇРєС– С” РІРёРґРё РїСЂРѕРіСЂР°Рј РћРџ?",
        canonical_question_uk="РЇРєС– С” РІРёРґРё РїСЂРѕРіСЂР°Рј РћРџ Сѓ Berry Land?",
        vector_query_uk="РІРёРґРё РѕСЂРіР°РЅС–Р·РѕРІР°РЅРёС… РїСЂРѕРіСЂР°Рј РћРџ Berry Land",
        lexical_keywords=["РїСЂРѕРіСЂР°РјРё", "РћРџ"],
        lexical_phrases=["РІРёРґРё РїСЂРѕРіСЂР°Рј РћРџ"],
        topic_hint="programs",
        direction_hints=["op"],
    )

    result = route_free_text_message(
        router=StaticRouter(route),
        context_store=_store(),
        context_key=_key(),
        message="РЇРєС– С” РІРёРґРё РїСЂРѕРіСЂР°Рј РћРџ?",
    )

    assert result.route is not None
    assert result.route.direction_hints == ["op"]
    assert result.should_search is True


def test_kb_query_without_topic_asks_topic_clarification() -> None:
    route = _route(
        "kb_query",
        original_message="Хочу уточнити інформацію",
        canonical_question_uk="Яка інформація про Berry Land цікавить користувача?",
        vector_query_uk="інформація Berry Land",
        lexical_keywords=["інформація"],
        lexical_phrases=["інформація Berry Land"],
        query_specificity="vague",
    )

    result = route_free_text_message(
        router=StaticRouter(route),
        context_store=_store(),
        context_key=_key(),
        message="Хочу уточнити інформацію",
    )

    assert result.route is not None
    assert result.should_search is False
    assert result.clarification_kind == "topic"
    assert "що саме вас цікавить" in result.response_text


def test_pending_topic_clarification_accepts_topic_then_asks_direction_if_needed() -> None:
    store = _store()
    context_key = _key()
    first_route = _route(
        "kb_query",
        original_message="Хочу уточнити інформацію",
        canonical_question_uk="Яка інформація про Berry Land цікавить користувача?",
        vector_query_uk="інформація Berry Land",
        lexical_keywords=["інформація"],
        lexical_phrases=["інформація Berry Land"],
        query_specificity="vague",
    )
    router = StaticRouter(first_route)

    first = route_free_text_message(
        router=router,
        context_store=store,
        context_key=context_key,
        message="Хочу уточнити інформацію",
    )
    second = route_free_text_message(
        router=router,
        context_store=store,
        context_key=context_key,
        message="квитки",
    )

    assert first.clarification_kind == "topic"
    assert second.route is not None
    assert second.route.topic_hint == "tickets"
    assert second.should_search is False
    assert second.clarification_kind == "direction"
    assert len(router.calls) == 1


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
            reasoning_effort="none",
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
        assert "temperature" not in call
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
    first_route = first_route.model_copy(update={"direction_hints": ["op"]})
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
    assert second.route is not None
    assert second.route.route == follow_up_route.route
    assert second.should_search is True
    assert second.used_context is True
    assert second.route.topic_hint == "tickets"
    assert second.route.direction_hints == ["op"]
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


def test_short_contextual_follow_up_recovers_when_llm_fails() -> None:
    store = _store()
    context_key = _key()
    first_route = _route(
        "kb_query",
        original_message="можно остаться на ночевку?",
        canonical_question_uk="Чи можна залишитися на ночівлю в Berry Land?",
        vector_query_uk="ночівля Berry Land",
        lexical_keywords=["ночівля"],
        lexical_phrases=["залишитися на ночівлю"],
        direction_hints=["camping"],
    )
    first = route_free_text_message(
        router=StaticRouter(first_route),
        context_store=store,
        context_key=context_key,
        message="можно остаться на ночевку?",
    )

    result = route_free_text_message(
        router=StaticRouter(error=RuntimeError("llm failed")),
        context_store=store,
        context_key=context_key,
        message="в які дні?",
    )

    assert first.should_search is True
    assert result.route is not None
    assert result.should_search is True
    assert result.used_context is True
    assert result.route.route == "follow_up"
    assert result.route.topic_hint == "schedule"
    assert result.route.direction_hints == ["camping"]
    assert "в які дні" in result.route.vector_query_uk


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


def test_reasoning_effort_can_be_omitted_for_legacy_models() -> None:
    parsed = _route("greeting")
    client = FakeOpenAIClient(parsed)
    router = OpenAIQueryRouter(
        api_key="test-key",
        model="legacy-model",
        timeout_seconds=7,
        reasoning_effort=None,
        client=client,
    )

    route = router.route("РџСЂРёРІС–С‚")

    assert route == parsed
    call = client.responses.calls[0]
    assert "reasoning" not in call
    assert "temperature" not in call


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
    assert "Recent turns:" in prompt_input
    assert "response_kind=search" in prompt_input


def test_context_history_keeps_last_four_turns() -> None:
    store = _store()
    context_key = _key()
    router = StaticRouter(
        *(
            _route("greeting", original_message=f"message {index}")
            for index in range(MAX_CONTEXT_TEST_TURNS)
        ),
    )

    for index in range(MAX_CONTEXT_TEST_TURNS):
        route_free_text_message(
            router=router,
            context_store=store,
            context_key=context_key,
            message=f"message {index}",
        )

    context = store.get(context_key)

    assert context is not None
    assert [turn.user_message for turn in context.history] == [
        "message 1",
        "message 2",
        "message 3",
        "message 4",
    ]


def test_router_failure_is_saved_as_fallback_context_turn() -> None:
    store = _store()
    context_key = _key()

    result = route_free_text_message(
        router=StaticRouter(error=RuntimeError("llm failed")),
        context_store=store,
        context_key=context_key,
        message="какие животные есть в парке?",
    )
    context = store.get(context_key)

    assert result.route is None
    assert result.should_search is False
    assert context is not None
    assert context.history[-1].route_name is None
    assert context.history[-1].response_kind == "fallback"


def test_context_store_can_attach_answer_metadata_to_last_turn() -> None:
    route = _route(
        "kb_query",
        canonical_question_uk="Які програми доступні в Berry Land?",
        vector_query_uk="організовані програми Berry Land",
        lexical_keywords=["програми"],
        lexical_phrases=["організовані програми"],
    )
    store = _store()
    context_key = _key()

    store.save(context_key, route)
    store.update_last_answer(
        context_key,
        answer_state="answered",
        accepted_candidate_ids=("programs:1",),
    )
    context = store.get(context_key)

    assert context is not None
    assert context.history[-1].answer_state == "answered"
    assert context.history[-1].accepted_candidate_ids == ("programs:1",)
