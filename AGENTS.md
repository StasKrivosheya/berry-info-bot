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

- Use `.env` for local Python and Docker Compose runs.
- Create it from `.env.example`.

## Safety rules

- Do not commit secrets or local env files (`.env.local`, `.env.docker`, `.env`)
- Keep architecture boundaries:
  - `core` for cross-cutting config/logging/constants
  - `api` for HTTP layer
  - `bot` for aiogram layer
  - `infra` for adapters
  - `bootstrap` for lifecycle wiring
