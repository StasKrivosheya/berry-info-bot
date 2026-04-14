# Stack Decision

The primary stack in this repository is Python 3.13.

Evidence:
- `pyproject.toml` defines the project metadata, Python dependency graph, and `requires-python = ">=3.13"`.
- The runtime entrypoint is `python -m app.main`.
- The application code lives under `src/app/...`.
- The repo uses FastAPI for HTTP operations and aiogram for the Telegram bot runtime.

Current baseline:
- Language: Python
- HTTP layer: FastAPI
- Bot layer: aiogram 3
- Test runner: pytest
- Linting: Ruff
