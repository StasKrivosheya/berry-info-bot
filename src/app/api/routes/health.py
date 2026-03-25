from __future__ import annotations

from fastapi import APIRouter

from app.core.constants import HEALTH_ENDPOINT_PATH, HEALTH_STATUS_OK

router = APIRouter(tags=["ops"])


@router.get(HEALTH_ENDPOINT_PATH)
async def health() -> dict[str, str]:
    """Operational readiness endpoint used by local checks and container probes."""

    return {"status": HEALTH_STATUS_OK}
