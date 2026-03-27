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

## Security note

- Never commit real secrets to tracked files.
- Keep real values only in local `.env.local` / `.env.docker`.
