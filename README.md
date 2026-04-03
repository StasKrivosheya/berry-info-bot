# berry-info-bot

Production-light, future-supportable backend skeleton for a Telegram bot.

## What this version does

- Runs FastAPI with `GET /health`
- Runs aiogram 3 long polling in the same process lifecycle
- Initializes async SQLAlchemy engine/session scaffold (`asyncpg`)
- Uses structured JSON logging
- Provides Windows-friendly task script and Unix `Makefile`
- Provides a scenario-driven Telegram menu with inline navigation and back flow
- Stores bot UI texts/links in typed resource maps (`StrEnum` keys)
- Handles keyword trigger `2026` and friendly fallbacks for unknown input

## Code map (where to add things)

- `src/app/main.py`: process entrypoint (`python -m app.main`)
- `src/app/bootstrap`: startup/shutdown orchestration for bot + DB
- `src/app/api`: FastAPI app factory and routes
- `src/app/bot`: aiogram factories, routers, handlers
- `src/app/infra`: infrastructure adapters (DB scaffold)
- `src/app/core`: configuration, constants, logging

When adding features:
- Add HTTP routes in `app/api/routes`
- Add Telegram handlers in `app/bot/handlers` and include them in `app/bot/routers`
- Add repositories/adapters in `app/infra`

## Environment strategy

This project intentionally separates local and docker env files because DB hostnames differ by runtime:

- Local Python run: DB host is `localhost`
- Docker Compose run: DB host is service name `db`

Create env files from templates:

```powershell
Copy-Item .env.local.example .env.local
Copy-Item .env.docker.example .env.docker
```

Required values:
- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL` (must start with `postgresql+asyncpg://`)
- `ADMIN_USER_IDS`

## Windows commands (recommended)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 install
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 lint
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test
```

Local run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 run
```

Docker run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 docker-up
```

Stop Docker:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 docker-down
```

## Unix-like commands

```bash
make install
make lint
make test
make run
make docker-up
make docker-down
```

## Quick test matrix

| Scenario | Setup | Command | Expected |
| --- | --- | --- | --- |
| Windows local app | `.env.local` configured, local Postgres available | `python -m app.main` | startup logs + `/health` returns 200 |
| Docker local stack | `.env.docker` configured | `docker compose up --build` | `app` + `db` run, `/health` returns 200 |
| Unit test | deps installed | `pytest -q` | all tests pass |
| Lint | deps installed | `ruff check src tests` | no violations |

Health check:

```bash
curl http://localhost:8080/health
```

Expected JSON:

```json
{"status":"ok"}
```

## Common failures and fixes

- `make` fails on Windows (`/usr/bin/make` not found):
  - Use `scripts/dev.ps1` commands instead.
- PowerShell blocks script execution:
  - Use `powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 <task>`.
- Startup fails with DB connection error:
  - Verify the right env file for the runtime (`.env.local` vs `.env.docker`).
  - Check `DATABASE_URL` host: `localhost` for local Python, `db` for Docker.
- Telegram auth/startup errors:
  - Verify bot token is valid and not revoked.
  - Ensure only one polling instance runs per token.

## JetBrains note (Windows)

JetBrains make-target configurations require GNU Make, which Windows does not ship by default.  
Use PowerShell run configurations that call `scripts/dev.ps1` tasks or direct Python commands.

## Knowledge-base CSV/XLSX parser

Use this parser to convert manually exported Google Sheets tabs into Markdown files for vector
store ingestion. Rich layout-heavy sheets should be exported as `.xlsx`; plain table-shaped tabs
can stay as `.csv`.

### Expected local folder structure

```text
data/
  knowledge_base/
    parser_config.toml
    raw_sources/
      01-faq.csv
      02-catalog.csv
      03-offers.xlsx
    processed/
      manifest.json
      markdown/
        01-faq.md
        02-catalog.md
        03-offers-family-day.md
```

Recommended source naming: `NN-topic-name.csv` or `NN-topic-name.xlsx`.
Local source exports in `data/knowledge_base/raw_sources` are ignored by Git, so you can drop real
customer workbooks there without staging them.
When workbook or sheet names use Cyrillic, the parser automatically transliterates them into
stable ASCII markdown filenames, so you do not need to rename tabs manually.

### Run parser

```powershell
.\.venv\Scripts\python.exe -m app.services.knowledge_base.cli
```

Custom paths:

```powershell
.\.venv\Scripts\python.exe -m app.services.knowledge_base.cli `
  --input-dir data/knowledge_base/raw_sources `
  --output-dir data/knowledge_base/processed `
  --config data/knowledge_base/parser_config.toml `
  --source-format xlsx
```

### Input/output behavior

- Discovers all `*.csv` and `*.xlsx` files in the input directory in lexicographic order.
- Reads CSV with strict decoding fallback (`utf-8-sig`, then `cp1251`) and strict CSV parsing.
- Reads visible workbook sheets from `.xlsx` exports and parses each visible sheet as a separate
  source unit.
- Supports per-sheet parser hints through `parser_config.toml` with `parser_profile` values:
  `qa_table`, `section_table`, `column_split`, and `outline_sheet`.
- Supports workbook-level `sheet_indexes = [1, 2, 3]` selection when you want to parse only
  specific tabs by their 1-based visible sheet order.
- Fails the workbook parse when configured `sheet_indexes` reference tabs that are not present
  among the currently visible sheets, instead of silently under-parsing.
- Supports format filtering through parser config (`[defaults].source_formats`) or CLI
  `--source-format` flags, for example XLSX-only runs while CSV parsing is temporarily disabled.
- Prefers conservative parsing for freeform workbook sheets:
  ambiguous heading/paragraph rows fail with diagnostics instead of being guessed.
- Removes previously generated markdown for a source before re-parsing it, so a newly failed sheet
  does not leave stale `.md` files behind in `processed/markdown`.
- Normalizes whitespace while preserving meaningful paragraph breaks.
- Drops fully empty rows and globally empty columns.
- Produces Markdown files in `processed/markdown` and writes one `processed/manifest.json`
  including source format, workbook/sheet metadata, and parser diagnostics for failures.
- Continues after file-level failures and returns non-zero exit code only if all files fail.

## OpenAI Vector Store Sync And Smoke Test

This project supports deterministic sync into an existing OpenAI vector store using replace-by-
`logical_id` semantics.

### Why replace by `logical_id` instead of append forever

- Prevents stale content accumulation when source markdown is regenerated.
- Ensures retrieval results reflect only the current KB version for each logical document.
- Keeps future admin-triggered refresh deterministic (`/kb_refresh` can call the same sync service).

### Sync command

```powershell
.\.venv\Scripts\python.exe .\scripts\kb_sync_vector_store.py --replace
```

Useful options:

```powershell
.\.venv\Scripts\python.exe .\scripts\kb_sync_vector_store.py `
  --manifest data/knowledge_base/processed/manifest.json `
  --dry-run `
  --only-category 02-Program-Description `
  --only-logical-id 02-program-description `
  --replace
```

Environment variables used by sync/search:

- `OPENAI_API_KEY`: authentication for OpenAI SDK.
- `OPENAI_VECTOR_STORE_ID`: target vector store id to sync/search.
- `OPENAI_KB_SEARCH_MAX_RESULTS`: optional override (strict default is `3`).
- `OPENAI_KB_SCORE_THRESHOLD`: optional override (strict default is `0.7`).

### Query interpretation policy and optional LLM fallback

The query pipeline stays rules-first. Deterministic classifier/scope/planner run first, and the
LLM is only an optional structured fallback for interpretation when policy allows it.

Environment variables:

- `KB_QUERY_LLM_MODE=disabled|fallback|forced`
- `KB_QUERY_LLM_ALLOWED_FOR=classifier,scope,planner,retrieval`
- `KB_QUERY_RULES_MIN_CONFIDENCE=0.85`
- `KB_QUERY_ENABLE_STAGE_RULES=true|false`
- `KB_QUERY_ENABLE_STAGE_SCOPE=true|false`
- `KB_QUERY_ENABLE_STAGE_PLANNER=true|false`
- `KB_QUERY_ENABLE_STAGE_RETRIEVAL=true|false`
- `KB_QUERY_ENABLE_STAGE_RENDERER=true|false`
- `KB_QUERY_LLM_MODEL=`: no hardcoded default; set this only when enabling LLM mode
- `KB_QUERY_LLM_TIMEOUT_SECONDS=10`
- `KB_QUERY_LLM_CACHE_SIZE=128`
- `KB_QUERY_LLM_MAX_RETRIEVAL_VARIANTS=1`

Recommended lightweight fallback model: `gpt-5.4-nano`.
The interpreter uses the Responses API with structured parsing and `reasoning={"effort":"none"}`.
The code does not force a specific model; it uses whatever `KB_QUERY_LLM_MODEL` is set to.
The same structured interpretation call can now also return retrieval hints:
primary retrieval query, optional alternate queries, and retrieval keywords.

Execution modes:

- `disabled`: current deterministic behavior only, no LLM calls.
- `fallback`: rules stay primary; LLM is used only for uncertain or disabled interpretation stages.
- `forced`: always use the LLM for the allowed interpretation stages so you can compare quality.

Behavior examples:

- Clear broad query in `disabled` or `fallback`:
  `Які є види організованих програм?` stays deterministic and skips the LLM.
- Ambiguous query in `fallback`:
  `Порадь щось для відпочинку` can trigger structured LLM interpretation and retrieval planning,
  then continues through the same app-controlled renderer/retrieval pipeline.
- Same ambiguous query by mode:
  `disabled` keeps deterministic safe fallback, `fallback` may call LLM only if needed, `forced`
  always routes interpretation through the LLM layer.
- Zoo/animal wording:
  `хто у вас є в зоопарку?` can be deterministically expanded toward Berry Land KB phrases such as
  `екскурсія на поні-ферму`, `тварини`, and `ранчо`, with LLM retrieval hints available as a
  second-layer refinement.

### Smoke test command

```powershell
.\.venv\Scripts\python.exe .\scripts\kb_smoke_test.py "how to register for the program?"
```

The smoke test prints top hits (score, filename, logical_id, category, excerpt). If no result is
relevant enough, it prints: `No relevant information found in the knowledge base.`
Use `--rewrite-query` to enable query rewriting when needed for experiments.

### Telegram dev command

For test/dev checks in chat, the bot also supports:

```text
/vs your question goes here
```

It returns one message per found result. Each message has:
- service block (score, file name, file id, logical_id, category, threshold/top score)
- text block (full found text, without excerpt trimming)

If no relevant result is found, it returns a service block with fallback status and the fallback text.
This command is intended for development/testing convenience.

`/vs` remains raw vector-search debug only. It does not use the LLM policy layer.

Additional temporary query-policy debug commands:

```text
/qclass your question
/qplan your question
/qroute your question
/qretrieve your question
/qanswer your question
```

What they show:

- `/qclass`: final classification and its source (`rules`, `llm`, or `default`).
- `/qplan`: final intent/scope/strategy plus retrieval plan, policy trace, and stage toggles.
- `/qroute`: policy-only trace, useful for manually checking when LLM fallback was requested.
- `/qretrieve`: retrieval plan plus executed queries, stop reason, and merged-hit counts.
- `/qanswer`: rendered answer plus the same routing metadata.

Manual evaluation flow:

1. Keep `KB_QUERY_LLM_MODE=disabled` and run `/qplan` for a few clear queries.
2. Switch to `KB_QUERY_LLM_MODE=fallback`, set `KB_QUERY_LLM_MODEL`, then compare `/qroute`,
   `/qretrieve`, and `/qanswer` for ambiguous queries.
3. Switch to `KB_QUERY_LLM_MODE=forced` to compare the LLM interpretation path against the
   deterministic path.
4. Tune the checked-in prompt guide at
   `src/app/services/knowledge_base/query/llm_prompt_guide.md` against the eval cases in
   `src/app/services/knowledge_base/query/llm_eval_cases.md`.
5. To mine fresh KB-native phrases from processed markdown, run:

```text
python scripts/export_kb_query_prompt_candidates.py
```

If the selected model is unavailable or at capacity, the app does not crash. The pipeline falls
back safely to deterministic behavior and the reason appears in debug output as
`llm_failure_reason=...`, especially via `/qroute`, `/qplan`, `/qretrieve`, or `/qanswer`.

## Security note

- Never commit real secrets to tracked files.
- Keep real values only in local `.env.local` / `.env.docker`.

