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

Parse CSV/XLSX exports into Markdown plus manifest:

```powershell
.\.venv\Scripts\python.exe -m app.services.knowledge_base.cli
```

Generated output:

- `data/knowledge_base/processed/manifest.json`
- `data/knowledge_base/processed/markdown/*.md`
- `data/knowledge_base/processed/kb_lexical.sqlite3`

The parser command rebuilds the local SQLite FTS5 lexical index after a successful parse. Use
`--skip-lexical-index` only when you need parser output without local search.

Sync generated Markdown into the OpenAI vector store:

```powershell
.\.venv\Scripts\python.exe .\scripts\kb_sync_vector_store.py --replace
```

Run a local vector-search smoke query:

```powershell
.\.venv\Scripts\python.exe .\scripts\kb_smoke_test.py "how to register?"
```

## Free-Text Routing

Commands, callbacks, exact menu buttons, and `2026` are handled deterministically. Other text
messages go through one structured OpenAI routing call that returns:

- route: `greeting`, `smalltalk`, `menu_help`, `follow_up`, `kb_query`, or `unsupported`
- Ukrainian canonical question and vector query for KB-searchable messages
- lexical keywords/phrases and optional category/logical hints

If the routing call is unavailable, the bot responds with a safe virtual-manager message and keeps
the menu buttons visible.

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
