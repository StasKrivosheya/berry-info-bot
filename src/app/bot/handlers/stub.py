from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router(name="stub")
START_STUB_MESSAGE = "Bot skeleton is running. No business logic is enabled yet."


@router.message(CommandStart())
async def start_stub_handler(message: Message) -> None:
    """Phase-1 wiring stub: replace with real features later."""

    await message.answer(START_STUB_MESSAGE)
