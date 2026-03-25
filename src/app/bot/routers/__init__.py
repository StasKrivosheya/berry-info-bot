from __future__ import annotations

from aiogram import Router

from app.bot.handlers.stub import router as stub_router


def build_root_router() -> Router:
    """Assemble the top-level bot router for easy future feature expansion."""

    root_router = Router(name="root")
    root_router.include_router(stub_router)
    return root_router
