from __future__ import annotations

import asyncio

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


def test_create_app_lifespan_starts_with_mocked_runtime_dependencies(monkeypatch) -> None:
    fake_bot = FakeBot()
    fake_dispatcher = FakeDispatcher()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DEBUG_COMMANDS_MODE", "disabled")
    monkeypatch.setenv("ADMIN_USER_IDS", "")
    get_settings.cache_clear()
    monkeypatch.setattr(lifespan, "create_bot", lambda token: fake_bot)
    monkeypatch.setattr(
        lifespan,
        "create_dispatcher",
        lambda admin_user_ids, *, debug_commands_mode: fake_dispatcher,
    )

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
