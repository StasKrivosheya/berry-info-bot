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
- `OPENAI_QUERY_ROUTER_REASONING_EFFORT`
- `OPENAI_ANSWER_MODEL`
- `OPENAI_ANSWER_REASONING_EFFORT`
- `OPENAI_VECTOR_STORE_ID`
- `KB_MANIFEST_PATH`
- `KB_LEXICAL_INDEX_PATH`

Useful defaults:

- `OPENAI_QUERY_ROUTER_MODEL=gpt-5.4-nano`
- `OPENAI_QUERY_ROUTER_REASONING_EFFORT=none`
- `OPENAI_QUERY_ROUTER_TIMEOUT_SECONDS=10`
- `OPENAI_ANSWER_MODEL=gpt-5.4-mini`
- `OPENAI_ANSWER_REASONING_EFFORT=low`
- `OPENAI_ANSWER_TIMEOUT_SECONDS=10`
- `OPENAI_KB_SEARCH_MAX_RESULTS=3`
- `OPENAI_KB_SCORE_THRESHOLD=0.5`
- `QUERY_CONTEXT_TTL_SECONDS=900`

The runtime reads `.env` only. `.env.local` is ignored by the app and should be treated only as a
legacy local file name. Do not commit `.env`, `.env.local`, `.env.docker`, or secrets.

Leave `OPENAI_QUERY_ROUTER_REASONING_EFFORT` or `OPENAI_ANSWER_REASONING_EFFORT` empty when using
a model that does not support the Responses API `reasoning` parameter.

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

When replacing or adding a brand-new XLSX file:

1. Put the workbook in `data/knowledge_base/raw_sources`. Raw workbooks are local/ignored files,
   so do not rely on Git to preserve them.
2. Inspect visible worksheet order and names before editing config. `sheet_indexes` use visible-tab
   order, not Excel's hidden-sheet order.
3. Update `data/knowledge_base/parser_config.toml`:
   - set the workbook's `sheet_indexes`;
   - add or update sheet-name comments for humans;
   - add `title` when the Markdown H1 should be cleaner than the first cell;
   - add `forced_header_rows` for short rows that must become headings;
   - add `forced_paragraph_rows` for scripts, prose, table rows, or cells whose first line looks
     like a heading but should stay body text;
   - add `ignore_rows` for spreadsheet-only headers, helper rows, obsolete notes, or duplicate
     table labels.
4. Update `data/knowledge_base/taxonomy.toml` with one `[[sources]]` mapping per useful tab:
   `source_file`, `sheet_name`, `direction_id`, `topic_ids`, and `period_label`.
5. Rebuild local Markdown, manifest, and SQLite FTS5 index:

   ```powershell
   .\.venv\Scripts\python.exe -m app.services.knowledge_base.cli
   ```

6. Check `data/knowledge_base/processed/manifest.json` before syncing. It should contain all
   expected tabs and `errors: []`.
7. Inspect generated headings in `data/knowledge_base/processed/markdown`. The best search files
   have one clear H1, meaningful H2/H3 sections, and no repeated table-label headings such as
   `NAME`, `DESCRIPTION`, or `PRICE`.
8. Run the local checks:

   ```powershell
   .\.venv\Scripts\ruff.exe check src tests
   .\.venv\Scripts\pytest.exe -q
   ```

9. Sync vector store with `--replace` after the local Markdown is clean. Use `--replace` whenever a
   source was removed, renamed, reordered, or materially changed.
10. Add/update eval cases in `tests/evals/qa_cases.yaml`, then manually test
    direction-sensitive questions.

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
   `direction_hints`, and optional `target_date`.
4. Hybrid search runs broad vector and local lexical retrieval.
5. `topic_hint` and `direction_hints` are ranking boosts, not hard filters.
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

## Runtime Cost Controls

- Router: default `gpt-5.4-nano` with `reasoning=none`.
- Answer generator: default `gpt-5.4-mini` with `reasoning=low`.
- Vector search count: `OPENAI_KB_SEARCH_MAX_RESULTS`.
- Local lexical search count: `DEFAULT_LEXICAL_MAX_RESULTS` in
  `src/app/services/knowledge_base/retrieval/lexical.py`.
- Answer LLM candidate cap: `ANSWER_INPUT_MAX_CANDIDATES` and
  `ANSWER_CANDIDATE_MAX_CHARS` in `src/app/services/knowledge_base/answer_generator.py`.
- Telegram free-text routing/search/answer runs via `asyncio.to_thread`; this avoids blocking the
  async bot loop and does not add extra OpenAI calls, tokens, vector searches, or API cost.

## Checks

```powershell
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\python.exe -m app.services.knowledge_base.cli
```

Opt-in real OpenAI evals are skipped by default:

```powershell
$env:RUN_OPENAI_EVALS='1'
.\.venv\Scripts\pytest.exe tests\test_openai_llm_evals.py -q
```

For quick vector-store smoke testing:

```powershell
.\.venv\Scripts\python.exe .\scripts\kb_smoke_test.py "Які є види програм?"
```
