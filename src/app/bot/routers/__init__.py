from __future__ import annotations

from aiogram import Router

from app.bot.handlers.scenarios import router as scenarios_router


def build_root_router() -> Router:
    """Assemble the top-level production bot router."""

    root_router = Router(name="root")
    root_router.include_router(scenarios_router)
    return root_router
