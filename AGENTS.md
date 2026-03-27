# AGENTS.md

Short guidance for contributors/automation agents working in this repository.

## Runtime and commands

- Windows-first command runner: `scripts/dev.ps1`
- Unix/CI command runner: `Makefile`
- Entry point: `python -m app.main`

Preferred checks before commit:

- `ruff check src tests`
- `pytest -q`

## Environment files

- Use `.env.local` for local Python run (DB host `localhost`)
- Use `.env.docker` for Docker Compose run (DB host `db`)
- Create from templates:
  - `.env.local.example`
  - `.env.docker.example`

## Safety rules

- Do not commit secrets or local env files (`.env.local`, `.env.docker`, `.env`)
- Keep architecture boundaries:
  - `core` for cross-cutting config/logging/constants
  - `api` for HTTP layer
  - `bot` for aiogram layer
  - `infra` for adapters
  - `bootstrap` for lifecycle wiring
