from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_NAVIGATION = "default"
SECTION_NAVIGATION = "section"


@dataclass(frozen=True, slots=True)
class ScenarioButton:
    """Button definition for scenario navigation or external links."""

    text: str
    target_node_id: str | None = None
    url: str | None = None

    def __post_init__(self) -> None:
        has_target = self.target_node_id is not None
        has_url = self.url is not None

        if has_target == has_url:
            msg = "ScenarioButton must define exactly one of target_node_id or url."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ScenarioNode:
    """Content + button payload for a single step in the scenario tree."""

    node_id: str
    title: str
    text: str
    photo_paths: tuple[Path, ...] = ()
    buttons: tuple[ScenarioButton, ...] = ()
    parent_node_id: str | None = None
    section_node_id: str | None = None
    navigation: str = DEFAULT_NAVIGATION
