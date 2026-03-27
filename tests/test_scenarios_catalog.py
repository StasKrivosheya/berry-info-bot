from __future__ import annotations

from app.bot.scenarios.catalog import MAIN_MENU_BACK_TARGET, SCENARIO_NODES


def test_each_node_has_matching_node_id_key() -> None:
    for node_id, node in SCENARIO_NODES.items():
        assert node.node_id == node_id


def test_each_navigation_target_exists() -> None:
    for node in SCENARIO_NODES.values():
        for button in node.buttons:
            if button.target_node_id is None:
                continue
            assert button.target_node_id in SCENARIO_NODES


def test_each_parent_reference_exists_or_points_to_main_menu() -> None:
    for node in SCENARIO_NODES.values():
        if node.parent_node_id is None:
            continue

        assert (
            node.parent_node_id == MAIN_MENU_BACK_TARGET
            or node.parent_node_id in SCENARIO_NODES
        )
