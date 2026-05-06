from __future__ import annotations

from aiogram import Bot, Dispatcher

from app.bot.middlewares import TraceContextMiddleware
from app.bot.routers import build_root_router


def create_bot(token: str) -> Bot:
    """Create Telegram bot client with shared default message formatting."""

    return Bot(token=token)


def create_dispatcher() -> Dispatcher:
    """Create dispatcher and inject starter shared context for future handlers."""

    dispatcher = Dispatcher()
    dispatcher.update.outer_middleware(TraceContextMiddleware())
    dispatcher.include_router(build_root_router())
    return dispatcher
