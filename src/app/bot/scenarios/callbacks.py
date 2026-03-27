from __future__ import annotations

from aiogram.filters.callback_data import CallbackData

NAV_ACTION_BACK = "back"
NAV_ACTION_OPEN = "open"


class ScenarioNavCallback(CallbackData, prefix="scn"):
    """Packed callback payload for scenario navigation buttons."""

    action: str
    node_id: str
