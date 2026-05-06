from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.bootstrap import lifespan
from app.core.config import get_settings
from app.core.constants import HEALTH_ENDPOINT_PATH, HEALTH_STATUS_OK
from app.main import create_app


class FakeBotSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeBot:
    def __init__(self) -> None:
        self.session = FakeBotSession()


class FakeDispatcher:
    def __init__(self) -> None:
        self.polling_started = asyncio.Event()

    def resolve_used_update_types(self) -> list[str]:
        return []

    async def start_polling(self, bot: FakeBot, *, allowed_updates: list[str]) -> None:
        self.polling_started.set()
        await asyncio.Event().wait()


def test_create_app_lifespan_starts_with_mocked_runtime_dependencies(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_bot = FakeBot()
    fake_dispatcher = FakeDispatcher()
    manifest_path = tmp_path / "manifest.json"
    lexical_index_path = tmp_path / "kb.sqlite3"
    manifest_path.write_text('{"entries": []}', encoding="utf-8")
    lexical_index_path.write_text("", encoding="utf-8")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_QUERY_ROUTER_MODEL", "test-router")
    monkeypatch.setenv("OPENAI_ANSWER_MODEL", "test-answer")
    monkeypatch.setenv("OPENAI_VECTOR_STORE_ID", "vs_test")
    monkeypatch.setenv("KB_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("KB_LEXICAL_INDEX_PATH", str(lexical_index_path))
    get_settings.cache_clear()
    monkeypatch.setattr(lifespan, "create_bot", lambda token: fake_bot)
    monkeypatch.setattr(lifespan, "create_dispatcher", lambda: fake_dispatcher)

    try:
        app = create_app()
        with TestClient(app) as client:
            response = client.get(HEALTH_ENDPOINT_PATH)

        assert response.status_code == 200
        assert response.json() == {"status": HEALTH_STATUS_OK}
        assert fake_bot.session.closed is True
        assert not hasattr(app.state.runtime, "database")
    finally:
        get_settings.cache_clear()
