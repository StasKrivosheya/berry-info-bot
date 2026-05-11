from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
    ReplyKeyboardMarkup,
)


@dataclass(frozen=True, slots=True)
class ChatUserKey:
    """Address user context in a chat to track previous interactive message."""

    chat_id: int
    user_id: int


ReplyMarkupType = InlineKeyboardMarkup | ReplyKeyboardMarkup | None
ALBUM_NAVIGATION_TEXT = "Навігація"


class ScenarioMessenger:
    """Send messages with previous-inline-keyboard cleanup policy."""

    def __init__(self) -> None:
        self._last_inline_message_ids: dict[ChatUserKey, int] = {}

    async def send(
        self,
        *,
        bot: Bot,
        chat_id: int,
        user_id: int,
        text: str,
        photo_paths: Sequence[Path] = (),
        reply_markup: ReplyMarkupType = None,
    ) -> Message:
        key = ChatUserKey(chat_id=chat_id, user_id=user_id)
        await self._clear_previous_inline_keyboard(bot=bot, key=key)

        if not photo_paths:
            sent_message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
            )
        else:
            sent_message = await self._send_photos(
                bot=bot,
                chat_id=chat_id,
                text=text,
                photo_paths=photo_paths,
                reply_markup=reply_markup,
            )

        if isinstance(reply_markup, InlineKeyboardMarkup):
            self._last_inline_message_ids[key] = sent_message.message_id
        else:
            self._last_inline_message_ids.pop(key, None)

        return sent_message

    async def _send_photos(
        self,
        *,
        bot: Bot,
        chat_id: int,
        text: str,
        photo_paths: Sequence[Path],
        reply_markup: ReplyMarkupType,
    ) -> Message:
        if len(photo_paths) == 1:
            return await bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(photo_paths[0]),
                caption=text or None,
                reply_markup=reply_markup,
            )

        sent_messages = await bot.send_media_group(
            chat_id=chat_id,
            media=[
                InputMediaPhoto(
                    media=FSInputFile(photo_path),
                    caption=(text or None) if index == 0 else None,
                )
                for index, photo_path in enumerate(photo_paths)
            ],
        )
        if reply_markup is not None:
            return await bot.send_message(
                chat_id=chat_id,
                text=ALBUM_NAVIGATION_TEXT,
                reply_markup=reply_markup,
            )
        return sent_messages[-1]

    async def _clear_previous_inline_keyboard(self, *, bot: Bot, key: ChatUserKey) -> None:
        previous_message_id = self._last_inline_message_ids.get(key)
        if previous_message_id is None:
            return

        with suppress(TelegramBadRequest):
            await bot.edit_message_reply_markup(
                chat_id=key.chat_id,
                message_id=previous_message_id,
                reply_markup=None,
            )

        self._last_inline_message_ids.pop(key, None)


def resolve_chat_id(message: Message | None) -> int | None:
    """Read chat id from callback message payload safely."""

    if message is None:
        return None
    return message.chat.id
