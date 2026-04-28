# berry-info-bot

Telegram bot backend for Berry Land information flows.

## Runtime

- Entrypoint: `python -m app.main`
- HTTP ops endpoint: `GET /health`
- Bot runtime: aiogram long polling managed by FastAPI lifespan
- Production bot behavior today: `/start`, `/menu`, scenario menu navigation, keyword `2026`, and
  friendly fallback responses for unknown text or non-text messages

The production app no longer starts PostgreSQL. The current MVP runtime only needs Telegram bot
polling plus the health endpoint.

## Configuration

Create local env files from templates:

```powershell
Copy-Item .env.local.example .env.local
Copy-Item .env.docker.example .env.docker
```

Required for bot startup:

- `TELEGRAM_BOT_TOKEN`

Common runtime settings:

- `APP_HOST`, `APP_PORT`, `LOG_LEVEL`
- `ADMIN_USER_IDS`
- `DEBUG_COMMANDS_MODE=disabled|admins|public`

`DEBUG_COMMANDS_MODE` defaults to `disabled`. Debug KB commands are not registered unless this value
is explicitly set to `admins` or `public`.

Required only for KB sync/search and future RAG work:

- `OPENAI_API_KEY`
- `OPENAI_QUERY_ROUTER_MODEL`
- `OPENAI_QUERY_ROUTER_TIMEOUT_SECONDS`
- `OPENAI_ANSWER_MODEL`
- `OPENAI_ANSWER_TIMEOUT_SECONDS`
- `OPENAI_VECTOR_STORE_ID`
- `OPENAI_KB_SEARCH_MAX_RESULTS`
- `OPENAI_KB_SCORE_THRESHOLD`
- `KB_LEXICAL_INDEX_PATH`
- `QUERY_CONTEXT_TTL_SECONDS`

Never commit real `.env.local`, `.env.docker`, or `.env` files.

## Commands

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 install
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 lint
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 run
```

Unix-like:

```bash
make install
make lint
make test
make run
```

Docker:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 docker-up
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 docker-down
```

## Checks

```powershell
ruff check src tests
pytest -q
```

## Knowledge Base

Raw local exports live in `data/knowledge_base/raw_sources` and are ignored by Git.

The production KB flow is driven by two configuration files:

- `data/knowledge_base/parser_config.toml`: which files/sheets to parse and parser hints.
- `data/knowledge_base/taxonomy.toml`: controlled business vocabulary for directions, topics,
  source mappings, and validity periods.

Parse CSV/XLSX exports into Markdown plus manifest:

```powershell
.\.venv\Scripts\python.exe -m app.services.knowledge_base.cli
```

Generated output:

- `data/knowledge_base/processed/manifest.json`
- `data/knowledge_base/processed/markdown/*.md`
- `data/knowledge_base/processed/kb_lexical.sqlite3`

The parser command enriches every source with controlled taxonomy metadata and rebuilds the local
SQLite FTS5 lexical index after a successful parse. Use `--skip-lexical-index` only when you need
parser output without local search.

Sync generated Markdown into the OpenAI vector store:

```powershell
.\.venv\Scripts\python.exe .\scripts\kb_sync_vector_store.py --replace
```

Run a local vector-search smoke query:

```powershell
.\.venv\Scripts\python.exe .\scripts\kb_smoke_test.py "how to register?"
```

### KB Taxonomy And Source Growth

The bot must not trust LLM-invented category names as production filters. Instead, the system owns a
controlled taxonomy in `data/knowledge_base/taxonomy.toml`.

Current core directions:

- `op`: `ОП`, organized programs.
- `sv`: `СВ`, family visits.
- `camping`: camping, currently inactive until a source is added.
- `birthdays`: `ДН`, birthdays, currently inactive until a source is added.
- `school_excursions`: `ШЕ`, school excursions, currently inactive until a source is added.

Current topic ids include:

- `tickets`
- `schedule`
- `programs`
- `transfer`
- `food`
- `contacts`
- `location`
- `rules`
- `services`
- `general`

Router model output uses `topic_hint`, `direction_hint`, and `target_date`. These values are
validated against `taxonomy.toml`. If the model returns an unknown value, the app treats it as
missing. Old `category_hint` values are not used as hard search filters.

Direction-sensitive topics such as `tickets`, `schedule`, `transfer`, `food`, `rules`, and
`services` require a clear direction. If the user asks “Скільки коштують квитки?” without saying
`ОП`, `СВ`, `Кемпінг`, etc., the bot asks a deterministic clarification instead of guessing.

Hybrid retrieval always searches broadly first:

- vector search uses OpenAI vector store with stable source attributes;
- lexical search uses local SQLite FTS5;
- `direction_hint` and `topic_hint` are ranking boosts, not mandatory filters;
- candidate deduplication uses stable section identity;
- answer generation can answer only from accepted candidates.

### Adding New KB Sources

Use this checklist whenever new sheets/files are added.

1. Put the raw export into `data/knowledge_base/raw_sources`.

2. Update `data/knowledge_base/parser_config.toml`:
   - add the source file if it is new;
   - select the relevant `sheet_indexes`;
   - add per-sheet parser hints such as `forced_header_rows` or `forced_paragraph_rows`;
   - set `ignore = true` for sheets that should not be part of production KB.

3. Update `data/knowledge_base/taxonomy.toml`:
   - if the direction is new, add or activate it under `[directions.<id>]`;
   - add aliases users may type, for example `ДН`, `день народження`, `ШЕ`;
   - add a `[[sources]]` block for each parsed sheet;
   - set `direction_id`;
   - set broad `topic_ids` covered by that sheet;
   - set `period_label`, for example `квітень-травень 2026`;
   - keep source mappings exact enough to avoid mixing `ОП`, `СВ`, `Кемпінг`, `ДН`, and `ШЕ`.

4. Rebuild processed KB and lexical index:
   ```powershell
   .\.venv\Scripts\python.exe -m app.services.knowledge_base.cli
   ```

5. Inspect generated files:
   - `data/knowledge_base/processed/manifest.json`
   - `data/knowledge_base/processed/markdown/*.md`
   - `data/knowledge_base/processed/kb_lexical.sqlite3`

6. Verify lexical search locally:
   ```powershell
   $env:PYTHONPATH='src'
   .\.venv\Scripts\python.exe -c "from app.services.knowledge_base.retrieval.lexical import SQLiteLexicalIndex; hits=SQLiteLexicalIndex().search(keywords=('квитки',), max_results=5); print(len(hits)); [print(h.candidate.direction_id, h.candidate.topic_ids, h.candidate.heading_path) for h in hits]"
   ```

7. Sync OpenAI vector store:
   ```powershell
   .\.venv\Scripts\python.exe .\scripts\kb_sync_vector_store.py --replace
   ```

   Use `--replace` when sources were removed, renamed, or materially changed. This prevents stale
   vector-store files from remaining attached.

8. Test representative Telegram questions:
   - explicit direction: `Скільки коштують квитки на СВ?`
   - ambiguous sensitive topic: `Скільки коштують квитки?`
   - OP program query: `Які є види програм?`
   - date-sensitive query: `Що працює у травні для сімейного відпочинку?`
   - no-evidence query: `Чи можна замовити вертоліт?`

9. Update eval cases when adding a new direction or source:
   - expected route;
   - expected `topic_hint`;
   - expected `direction_hint` or expected clarification;
   - at least one expected source/direction for answerable cases.

10. Remove stale knowledge deliberately:
    - remove or deactivate old source mappings in `taxonomy.toml`;
    - remove ignored/obsolete sheets from `parser_config.toml`;
    - rerun parser;
    - run vector sync with `--replace`;
    - verify old wording no longer appears in lexical search or vector smoke tests.

## Free-Text Routing

Commands, callbacks, exact menu buttons, and `2026` are handled deterministically. Other text
messages go through one structured OpenAI routing call that returns:

- route: `greeting`, `smalltalk`, `menu_help`, `follow_up`, `kb_query`, or `unsupported`
- Ukrainian canonical question and vector query for KB-searchable messages
- lexical keywords/phrases
- controlled `topic_hint`, `direction_hint`, and optional `target_date`

If the routing call is unavailable, the bot responds with a safe virtual-manager message and keeps
the menu buttons visible.

KB answers are evidence-only. The answer model receives bounded hybrid-search candidates as
untrusted data and must either answer from accepted candidates or return the fixed not-found
fallback.

## Debug Commands

Debug commands are excluded from the production router by default.

To enable them for a controlled environment, set:

```text
DEBUG_COMMANDS_MODE=admins
ADMIN_USER_IDS=123456789
```

Available debug commands when enabled:

- `/vs`
- `/qclass`
- `/qplan`
- `/qroute`
- `/qretrieve`
- `/qanswer`
