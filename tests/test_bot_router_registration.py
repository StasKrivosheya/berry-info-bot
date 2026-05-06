from __future__ import annotations

from aiogram import Router

from app.bot.factory import create_dispatcher


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
