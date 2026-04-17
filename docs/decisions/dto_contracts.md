# DTO Contracts Decision

The query pipeline now exposes stable DTO contracts for stage boundaries while keeping the legacy query models as compatibility adapters for existing renderer and debug flows.

## Why dataclasses

- The repository already uses frozen and slotted dataclasses for domain models.
- Pydantic is used mainly for settings and OpenAI response payload validation.
- Matching the existing style keeps the DTO layer lightweight and consistent.

## DTO schema

### `NormalizedQuery`

- `raw_text: str`
- `user_locale: str`
- `detected_language: str`
- `canonical_uk: str`
- `created_at: datetime`

Notes:
- `created_at` is serialized as UTC ISO 8601.
- `canonical_uk` is the normalized Ukrainian query text used by downstream stages.

### `RouterDecision`

- `intent: str`
- `needs_clarification: bool`
- `clarification_question: str | None`
- `missing_slots: tuple[str, ...]`
- `routing_flags: { scope, scopes, strategy, needs_retrieval, needs_structure, policy_mode, intent_source, scope_source, strategy_source, retrieval_source }`

Defaults:
- `clarification_question` defaults to `None`.
- `missing_slots` defaults to an empty tuple.

### `RewriteResult`

- `canonical_uk: str`
- `vector_query_uk: str`
- `lexical: { keywords, synonyms, phrases }`
- `filters: { category, logical_id, language, attribute_filters }`

Notes:
- `lexical.keywords` comes from retrieval keywords.
- `lexical.synonyms` comes from alternate retrieval queries.
- `lexical.phrases` includes the canonical query plus the vector query phrases.
- `filters.attribute_filters` stores the merged retrieval filter payload.

### `VectorHit`

- `section_id: str`
- `file_id: str`
- `score: float`
- `text: str`
- `attributes: dict[str, str | int | float | bool]`

Notes:
- `section_id` is derived from logical document id plus the resolved heading path when available.
- `attributes.heading_path` is added when structure resolution succeeds.

### `LexicalHit`

- `section_id: str`
- `bm25: float`
- `heading_path: tuple[str, ...]`
- `content: str`

Current behavior:
- The lexical stage is intentionally stubbed in this refactor and returns an empty collection until a real lexical retriever is introduced.

### `EvidenceItem`

- `section_id: str`
- `source_type: "vector" | "lexical"`
- `title: str`
- `content: str`
- `score: float`

### `EvidencePacket`

- `items: tuple[EvidenceItem, ...]`
- `token_budget_used: int`
- `truncation_applied: bool`

Defaults:
- The current pipeline includes all evidence unless an explicit token budget is passed to the evidence builder.

### `AnswerResult`

- `state: "answered" | "clarification" | "fallback"`
- `answer_text: str`
- `clarification_question: str | None`
- `source_section_ids: tuple[str, ...]`
- `debug_reason: str | None`

State mapping:
- `answered` for normal successful responses.
- `fallback` when the legacy pipeline marks the answer as fallback.
- `clarification` is reserved for future question-asking flows when a clarification prompt is available.

## Serialization contract

- Every DTO supports `to_dict`, `from_dict`, `to_json`, and `from_json`.
- Tuple fields serialize as JSON arrays and deserialize back to tuples.
- Datetime fields deserialize to timezone-aware UTC values.

## Compatibility notes

- `KnowledgeBaseQueryPipeline.answer_query_dto(...)` is the DTO-first answer surface.
- `KnowledgeBaseQueryPipeline.answer_query(...)` remains the compatibility surface and is backed by the same contract run.
- Existing `QueryPlan`, `QueryAnswerResult`, `SearchHit`, and `SearchResponse` types are still used internally where renderer/debug code depends on them, but stage contract handoffs are normalized through the new DTO layer.
