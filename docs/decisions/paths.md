# Path Decision

The task prompt suggested `src/` or `app/`, but this repository uses a packaged source layout rooted at `src/app`.

Implemented observability paths:
- `src/app/observability/tracing.py`
- `src/app/observability/logger.py`

Related integration paths:
- `src/app/bot/middlewares/tracing.py`
- `src/app/core/logging.py`
- `src/app/services/knowledge_base/query/pipeline.py`

Reason:
- `pyproject.toml` configures setuptools with `package-dir = {"" = "src"}`.
- Existing modules are consistently imported as `app.<module>`.
