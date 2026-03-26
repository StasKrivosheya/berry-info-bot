from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.factory import create_api_app
from app.core.constants import HEALTH_ENDPOINT_PATH, HEALTH_STATUS_OK


def test_health_returns_ok() -> None:
    app = create_api_app(app_name="test-app")
    with TestClient(app) as client:
        response = client.get(HEALTH_ENDPOINT_PATH)

    assert response.status_code == 200
    assert response.json() == {"status": HEALTH_STATUS_OK}
