from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.constants import HEALTH_ENDPOINT_PATH, HEALTH_STATUS_OK

router = APIRouter(tags=["ops"])
HEALTH_STATUS_DEGRADED = "degraded"
HEALTH_REASON_POLLING_FAILED = "telegram_polling_failed"


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

    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": HEALTH_STATUS_OK})
