# berry-info-bot

Telegram bot for Berry Land visitor questions. The MVP serves deterministic menu flows and a
production RAG path for free-text questions over the local knowledge base.

## Architecture

- `app.main`: FastAPI app plus aiogram long polling lifecycle.
- `app.bot`: Telegram commands, menu callbacks, and free-text handlers.
- `app.services.knowledge_base.query_router`: one structured LLM call for routing and
  canonicalization.
- `app.services.knowledge_base.retrieval`: OpenAI vector-store search plus local SQLite FTS5
  lexical search.
- `app.services.knowledge_base.answer_generator`: evidence-only structured answer generation.
- `data/knowledge_base/taxonomy.toml`: controlled directions/topics used by ingest and routing.

There is no production database service in the MVP.

## Environment

Create one runtime env file:

```powershell
Copy-Item .env.example .env
```

Required:

- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `OPENAI_QUERY_ROUTER_MODEL`
- `OPENAI_ANSWER_MODEL`
- `OPENAI_VECTOR_STORE_ID`
- `KB_MANIFEST_PATH`
- `KB_LEXICAL_INDEX_PATH`

Useful defaults:

- `OPENAI_QUERY_ROUTER_TIMEOUT_SECONDS=10`
- `OPENAI_ANSWER_TIMEOUT_SECONDS=10`
- `OPENAI_KB_SEARCH_MAX_RESULTS=3`
- `OPENAI_KB_SCORE_THRESHOLD=0.5`
- `QUERY_CONTEXT_TTL_SECONDS=900`

Do not commit `.env`, `.env.local`, `.env.docker`, or secrets.

## Local Run

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 install
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m app.services.knowledge_base.cli
.\.venv\Scripts\python.exe .\scripts\kb_sync_vector_store.py --replace
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 run
```

Health endpoint:

```text
GET /health
```

Readiness returns `503` if Telegram polling failed, required OpenAI/vector settings are missing, or
the KB manifest / lexical index files are absent.

## Production Deploy

Docker Compose runs only the app service:

```powershell
Copy-Item .env.example .env
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 docker-up
```

Before deploy, build or mount KB artifacts:

- `data/knowledge_base/processed/manifest.json`
- `data/knowledge_base/processed/kb_lexical.sqlite3`
- synced OpenAI vector store matching `OPENAI_VECTOR_STORE_ID`

The app does not rebuild KB automatically on startup.

## KB Rebuild

Raw exports go into `data/knowledge_base/raw_sources` and are ignored by Git.

Controlled files:

- `data/knowledge_base/parser_config.toml`: source files, sheet indexes, parser hints.
- `data/knowledge_base/taxonomy.toml`: business directions, topics, source mappings, periods.

Rebuild local Markdown, manifest, and SQLite FTS5 index:

```powershell
.\.venv\Scripts\python.exe -m app.services.knowledge_base.cli
```

Sync Markdown to OpenAI vector store:

```powershell
.\.venv\Scripts\python.exe .\scripts\kb_sync_vector_store.py --replace
```

Use `--replace` when a source was removed, renamed, or materially changed so stale vector-store
files are deleted.

When adding new sources:

1. Add the raw XLSX/CSV.
2. Update `parser_config.toml`.
3. Add or activate the direction/topic mapping in `taxonomy.toml`.
4. Rebuild local KB.
5. Sync vector store with `--replace`.
6. Add/update eval cases in `tests/evals/qa_cases.yaml`.
7. Test direction-sensitive questions manually.

Current active directions:

- `op`: ОП, організовані програми.
- `sv`: СВ, сімейний відпочинок.

Future inactive directions are already named in taxonomy: `camping`, `birthdays`,
`school_excursions`.

## Telegram User Stories

- User opens `/start` or `/menu`: bot shows deterministic menu.
- User taps buttons or exact menu keywords: bot stays deterministic.
- User writes a greeting or smalltalk: bot returns short service text.
- User asks a KB question: bot routes, searches, and answers only from evidence.
- User asks about price/schedule/transfer without a direction: bot asks which direction to use.
- User asks something absent from KB: bot returns the fixed not-found fallback.

## RAG Flow

1. Commands, callbacks, and exact menu labels are handled without LLM.
2. Normal free text goes to one structured routing/canonicalization call.
3. Router returns route, Ukrainian canonical question, vector query, lexical terms, `topic_hint`,
   `direction_hint`, and optional `target_date`.
4. Hybrid search runs broad vector and lexical retrieval.
5. `topic_hint` and `direction_hint` are ranking boosts, not hard filters.
6. Candidate IDs are deduplicated and bounded.
7. Answer model receives candidates as untrusted data.
8. If accepted evidence is empty or insufficient, answer is exactly:

```text
Такого не знайшлось в базі знань. Спробуйте зателефонувати менеджеру для більш детальної консультації.
```

## Limitations

- No visible citations in Telegram answers yet.
- No automatic KB rebuild on startup.
- Direction/date ambiguity is intentionally conservative.
- Answer quality depends on KB source freshness and vector-store sync.

## Checks

```powershell
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\python.exe -m app.services.knowledge_base.cli
```

For quick vector-store smoke testing:

```powershell
.\.venv\Scripts\python.exe .\scripts\kb_smoke_test.py "Які є види програм?"
```
