from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.bot.scenarios.models import ScenarioButton, ScenarioNode

DEFAULT_SCENARIO_CONFIG_PATH = Path("data/bot_scenarios/menu.toml")


@dataclass(frozen=True, slots=True)
class ScenarioCatalog:
    """Loaded bot menu tree."""

    nodes: dict[str, ScenarioNode]
    main_menu_actions: dict[str, str]


def load_scenario_catalog(
    config_path: Path = DEFAULT_SCENARIO_CONFIG_PATH,
    *,
    main_menu_back_target: str,
) -> ScenarioCatalog:
    """Load editable bot menu content from TOML and Markdown files."""

    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    base_dir = config_path.parent
    main_menu_node_ids = _str_list(raw.get("main_menu"), field="main_menu")
    raw_nodes = _dict(raw.get("nodes"), field="nodes")

    parent_by_child = _build_parent_map(
        raw_nodes=raw_nodes,
        main_menu_node_ids=main_menu_node_ids,
        main_menu_back_target=main_menu_back_target,
    )

    nodes: dict[str, ScenarioNode] = {}
    for node_id, raw_node in raw_nodes.items():
        node_config = _dict(raw_node, field=f"nodes.{node_id}")
        title = _required_str(node_config, "title", field=f"nodes.{node_id}.title")
        children = _str_list(
            node_config.get("children", ()),
            field=f"nodes.{node_id}.children",
        )
        buttons = [
            ScenarioButton(
                text=_node_title(raw_nodes, child_id),
                target_node_id=child_id,
            )
            for child_id in children
        ]
        buttons.extend(_load_link_buttons(node_config, node_id=node_id))

        nodes[node_id] = ScenarioNode(
            node_id=node_id,
            title=title,
            text=_load_node_text(node_config, base_dir=base_dir, fallback_title=title),
            photo_path=_load_photo_path(node_config, base_dir=base_dir, node_id=node_id),
            buttons=tuple(buttons),
            parent_node_id=parent_by_child.get(node_id),
        )

    return ScenarioCatalog(
        nodes=nodes,
        main_menu_actions={
            _node_title(raw_nodes, node_id): node_id for node_id in main_menu_node_ids
        },
    )


def _build_parent_map(
    *,
    raw_nodes: dict[str, Any],
    main_menu_node_ids: list[str],
    main_menu_back_target: str,
) -> dict[str, str]:
    parent_by_child: dict[str, str] = {}

    for node_id in main_menu_node_ids:
        _ensure_node_exists(raw_nodes, node_id)
        parent_by_child[node_id] = main_menu_back_target

    for parent_id, raw_node in raw_nodes.items():
        node_config = _dict(raw_node, field=f"nodes.{parent_id}")
        child_ids = _str_list(
            node_config.get("children", ()),
            field=f"nodes.{parent_id}.children",
        )
        for child_id in child_ids:
            _ensure_node_exists(raw_nodes, child_id)
            existing_parent = parent_by_child.get(child_id)
            if existing_parent is not None:
                msg = f"Scenario node {child_id!r} is already attached to {existing_parent!r}."
                raise ValueError(msg)
            parent_by_child[child_id] = parent_id

    return parent_by_child


def _load_link_buttons(node_config: dict[str, Any], *, node_id: str) -> list[ScenarioButton]:
    buttons = []
    for index, raw_link in enumerate(
        _list(node_config.get("links", ()), field=f"nodes.{node_id}.links"),
    ):
        link = _dict(raw_link, field=f"nodes.{node_id}.links[{index}]")
        buttons.append(
            ScenarioButton(
                text=_required_str(link, "title", field=f"nodes.{node_id}.links[{index}].title"),
                url=_required_str(link, "url", field=f"nodes.{node_id}.links[{index}].url"),
            ),
        )
    return buttons


def _load_node_text(node_config: dict[str, Any], *, base_dir: Path, fallback_title: str) -> str:
    content_text = node_config.get("content_text")
    if content_text is not None:
        path = base_dir / _str(content_text, field="content_text")
        return path.read_text(encoding="utf-8").strip()

    inline_text = node_config.get("text")
    if inline_text is not None:
        return _str(inline_text, field="text").strip()

    return f"Інформація про {fallback_title}"


def _load_photo_path(node_config: dict[str, Any], *, base_dir: Path, node_id: str) -> Path | None:
    content_photo = node_config.get("content_photo")
    if content_photo is None:
        return None

    path = base_dir / _str(content_photo, field=f"nodes.{node_id}.content_photo")
    if not path.is_file():
        msg = f"Scenario photo file does not exist: {path}"
        raise ValueError(msg)
    return path


def _node_title(raw_nodes: dict[str, Any], node_id: str) -> str:
    _ensure_node_exists(raw_nodes, node_id)
    node_config = _dict(raw_nodes[node_id], field=f"nodes.{node_id}")
    return _required_str(node_config, "title", field=f"nodes.{node_id}.title")


def _ensure_node_exists(raw_nodes: dict[str, Any], node_id: str) -> None:
    if node_id not in raw_nodes:
        msg = f"Scenario node {node_id!r} is referenced but not defined."
        raise ValueError(msg)


def _required_str(data: dict[str, Any], key: str, *, field: str) -> str:
    return _str(data.get(key), field=field)


def _str(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        msg = f"Expected non-empty string for {field}."
        raise ValueError(msg)
    return value.strip()


def _str_list(value: Any, *, field: str) -> list[str]:
    return [_str(item, field=f"{field}[]") for item in _list(value, field=field)]


def _list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list | tuple):
        msg = f"Expected list for {field}."
        raise ValueError(msg)
    return list(value)


def _dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        msg = f"Expected table for {field}."
        raise ValueError(msg)
    return value
