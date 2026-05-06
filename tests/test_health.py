from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.factory import create_api_app
from app.core.config import Settings
from app.core.constants import HEALTH_ENDPOINT_PATH, HEALTH_STATUS_OK


def test_health_returns_ok() -> None:
    app = create_api_app(app_name="test-app")
    with TestClient(app) as client:
        response = client.get(HEALTH_ENDPOINT_PATH)

    assert response.status_code == 200
    assert response.json() == {"status": HEALTH_STATUS_OK}


def test_health_returns_503_when_polling_failed() -> None:
    app = create_api_app(app_name="test-app")
    app.state.runtime = SimpleNamespace(
        polling_exception=RuntimeError("boom"),
        polling_task=None,
    )

    with TestClient(app) as client:
        response = client.get(HEALTH_ENDPOINT_PATH)

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "reason": "telegram_polling_failed",
    }


def test_health_returns_503_when_kb_runtime_is_not_ready(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="123456:TEST_TOKEN",
        OPENAI_API_KEY="test-key",
        OPENAI_QUERY_ROUTER_MODEL="router",
        OPENAI_ANSWER_MODEL="answer",
        OPENAI_VECTOR_STORE_ID="vs_test",
        KB_MANIFEST_PATH=tmp_path / "missing-manifest.json",
        KB_LEXICAL_INDEX_PATH=tmp_path / "missing.sqlite3",
    )
    app = create_api_app(app_name="test-app", settings=settings)

    with TestClient(app) as client:
        response = client.get(HEALTH_ENDPOINT_PATH)

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["reason"] == "runtime_not_ready"
    assert any(item.startswith("KB_MANIFEST_PATH:") for item in payload["missing"])
