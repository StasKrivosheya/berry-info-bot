from __future__ import annotations

import asyncio

from aiogram import Router

from app.bot.factory import create_bot, create_dispatcher


def _router_names(router: Router) -> set[str]:
    names = {router.name}
    for child in router.sub_routers:
        names.update(_router_names(child))
    return names


def test_production_dispatcher_registers_only_production_router() -> None:
    dispatcher = create_dispatcher()

    registered_names: set[str] = set()
    for router in dispatcher.sub_routers:
        registered_names.update(_router_names(router))

    assert "root" in registered_names
    assert "scenarios" in registered_names
    assert "query-debug" not in registered_names


def test_production_bot_has_no_global_html_parse_mode() -> None:
    bot = create_bot("123456:TEST_TOKEN")

    try:
        assert bot.default.parse_mode is None
    finally:
        asyncio.run(bot.session.close())
