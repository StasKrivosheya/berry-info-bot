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

## Knowledge-base CSV parser

Use this parser to convert manually exported Google Sheets CSV tabs into Markdown files for vector
store ingestion.

### Expected local folder structure

```text
data/
  knowledge_base/
    parser_config.toml
    raw_csv/
      01-faq.csv
      02-catalog.csv
    processed/
      manifest.json
      markdown/
        01-faq.md
        02-catalog.md
```

Recommended CSV naming: `NN-topic-name.csv` (for deterministic ordering and readable output).

### Run parser

```powershell
.\.venv\Scripts\python.exe -m app.services.knowledge_base.cli
```

Custom paths:

```powershell
.\.venv\Scripts\python.exe -m app.services.knowledge_base.cli `
  --input-dir data/knowledge_base/raw_csv `
  --output-dir data/knowledge_base/processed `
  --config data/knowledge_base/parser_config.toml
```

### Input/output behavior

- Discovers all `*.csv` files in the input directory in lexicographic order.
- Reads CSV with strict decoding fallback (`utf-8-sig`, then `cp1251`) and strict CSV parsing.
- Normalizes whitespace while preserving meaningful paragraph breaks.
- Drops fully empty rows and globally empty columns.
- Produces Markdown files in `processed/markdown` and writes one `processed/manifest.json`.
- Continues after file-level failures and returns non-zero exit code only if all files fail.

## Security note

- Never commit real secrets to tracked files.
- Keep real values only in local `.env.local` / `.env.docker`.
