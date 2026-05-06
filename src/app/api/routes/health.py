from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.config import Settings
from app.core.constants import HEALTH_ENDPOINT_PATH, HEALTH_STATUS_OK

router = APIRouter(tags=["ops"])
HEALTH_STATUS_DEGRADED = "degraded"
HEALTH_REASON_POLLING_FAILED = "telegram_polling_failed"
HEALTH_REASON_NOT_READY = "runtime_not_ready"


@router.get(HEALTH_ENDPOINT_PATH)
async def health(request: Request) -> JSONResponse:
    """Operational readiness endpoint used by local checks and container probes."""

    runtime = getattr(request.app.state, "runtime", None)
    polling_exception = getattr(runtime, "polling_exception", None)
    polling_task = getattr(runtime, "polling_task", None)
    polling_stopped = (
        polling_task is not None
        and polling_task.done()
        and not polling_task.cancelled()
    )
    if polling_exception is not None or polling_stopped:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": HEALTH_STATUS_DEGRADED,
                "reason": HEALTH_REASON_POLLING_FAILED,
            },
        )

    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        missing = _readiness_gaps(settings)
        if missing:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": HEALTH_STATUS_DEGRADED,
                    "reason": HEALTH_REASON_NOT_READY,
                    "missing": missing,
                },
            )

    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": HEALTH_STATUS_OK})


def _readiness_gaps(settings: Settings) -> list[str]:
    missing: list[str] = []
    if settings.openai_api_key_value is None:
        missing.append("OPENAI_API_KEY")
    if settings.openai_query_router_model is None:
        missing.append("OPENAI_QUERY_ROUTER_MODEL")
    if settings.openai_answer_model is None:
        missing.append("OPENAI_ANSWER_MODEL")
    if settings.openai_vector_store_id is None:
        missing.append("OPENAI_VECTOR_STORE_ID")
    if not settings.kb_manifest_path.exists():
        missing.append(f"KB_MANIFEST_PATH:{settings.kb_manifest_path.as_posix()}")
    if not settings.kb_lexical_index_path.exists():
        missing.append(f"KB_LEXICAL_INDEX_PATH:{settings.kb_lexical_index_path.as_posix()}")
    return missing
