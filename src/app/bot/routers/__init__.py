from __future__ import annotations

from aiogram import Router

from app.bot.handlers.debug.query_debug import router as query_debug_router
from app.bot.handlers.scenarios import router as scenarios_router


def build_root_router(*, include_debug_commands: bool = True) -> Router:
    """Assemble the top-level bot router for easy future feature expansion."""

    root_router = Router(name="root")
    if include_debug_commands:
        root_router.include_router(query_debug_router)
    root_router.include_router(scenarios_router)
    return root_router

