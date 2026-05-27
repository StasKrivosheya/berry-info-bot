from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.bot.scenarios.navigation import ALBUM_NAVIGATION_TEXT, ScenarioMessenger


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.photos: list[dict[str, object]] = []
        self.media_groups: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> SimpleNamespace:
        self.messages.append(kwargs)
        return SimpleNamespace(message_id=1)

    async def send_photo(self, **kwargs: object) -> SimpleNamespace:
        self.photos.append(kwargs)
        return SimpleNamespace(message_id=2)

    async def send_media_group(self, **kwargs: object) -> list[SimpleNamespace]:
        self.media_groups.append(kwargs)
        return [SimpleNamespace(message_id=2), SimpleNamespace(message_id=3)]

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
            photo_paths=(photo_path,),
        ),
    )

    assert bot.messages == []
    assert len(bot.photos) == 1
    assert bot.photos[0]["chat_id"] == 10
    assert bot.photos[0]["caption"] == "Presenter caption"


def test_scenario_messenger_sends_multiple_photo_presenters(tmp_path: Path) -> None:
    first_photo_path = tmp_path / "first.png"
    second_photo_path = tmp_path / "second.png"
    first_photo_path.write_bytes(b"image")
    second_photo_path.write_bytes(b"image")
    bot = FakeBot()
    messenger = ScenarioMessenger()
    reply_markup = object()

    asyncio.run(
        messenger.send(
            bot=bot,
            chat_id=10,
            user_id=20,
            text="Presenter caption",
            photo_paths=(first_photo_path, second_photo_path),
            reply_markup=reply_markup,
        ),
    )

    assert bot.photos == []
    assert len(bot.media_groups) == 1
    assert len(bot.media_groups[0]["media"]) == 2
    assert bot.messages == [
        {
            "chat_id": 10,
            "text": ALBUM_NAVIGATION_TEXT,
            "reply_markup": reply_markup,
        },
    ]
