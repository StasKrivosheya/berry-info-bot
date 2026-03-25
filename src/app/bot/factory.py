from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot.routers import build_root_router

DISPATCHER_CONTEXT_ADMIN_USER_IDS = "admin_user_ids"
BOT_DEFAULT_PARSE_MODE = ParseMode.HTML


def create_bot(token: str) -> Bot:
    """Create Telegram bot client with shared default message formatting."""

    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=BOT_DEFAULT_PARSE_MODE),
    )


def create_dispatcher(admin_user_ids: tuple[int, ...]) -> Dispatcher:
    """Create dispatcher and inject starter shared context for future handlers."""

    dispatcher = Dispatcher()
    dispatcher[DISPATCHER_CONTEXT_ADMIN_USER_IDS] = set(admin_user_ids)
    dispatcher.include_router(build_root_router())
    return dispatcher
