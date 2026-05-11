from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.bot.scenarios.navigation import ScenarioMessenger


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.photos: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> SimpleNamespace:
        self.messages.append(kwargs)
        return SimpleNamespace(message_id=1)

    async def send_photo(self, **kwargs: object) -> SimpleNamespace:
        self.photos.append(kwargs)
        return SimpleNamespace(message_id=2)

    async def edit_message_reply_markup(self, **kwargs: object) -> None:
        return None


def test_scenario_messenger_sends_photo_presenter(tmp_path: Path) -> None:
    photo_path = tmp_path / "presenter.png"
    photo_path.write_bytes(b"image")
    bot = FakeBot()
    messenger = ScenarioMessenger()

    asyncio.run(
        messenger.send(
            bot=bot,
            chat_id=10,
            user_id=20,
            text="Presenter caption",
            photo_path=photo_path,
        ),
    )

    assert bot.messages == []
    assert len(bot.photos) == 1
    assert bot.photos[0]["chat_id"] == 10
    assert bot.photos[0]["caption"] == "Presenter caption"
