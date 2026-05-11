from __future__ import annotations

from pathlib import Path

import pytest

from app.bot.scenarios.loader import load_scenario_catalog


def test_load_scenario_catalog_reads_tree_text_links_and_photo(tmp_path: Path) -> None:
    (tmp_path / "texts").mkdir()
    (tmp_path / "media").mkdir()
    (tmp_path / "texts" / "root.md").write_text("Root text\n", encoding="utf-8")
    (tmp_path / "texts" / "section.md").write_text("Section text\n", encoding="utf-8")
    (tmp_path / "texts" / "child.md").write_text("Child text\n", encoding="utf-8")
    (tmp_path / "media" / "child.png").write_bytes(b"image")
    (tmp_path / "media" / "child-2.png").write_bytes(b"image")
    config_path = tmp_path / "menu.toml"
    config_path.write_text(
        """
main_menu = ["root"]

[nodes.root]
title = "Root"
content_text = "texts/root.md"
children = ["section"]
links = [
  { title = "Site", url = "https://example.com" },
]

[nodes.section]
title = "Section"
content_text = "texts/section.md"
children = ["child"]

[nodes.child]
title = "Child"
content_text = "texts/child.md"
content_photos = ["media/child.png", "media/child-2.png"]
""",
        encoding="utf-8",
    )

    catalog = load_scenario_catalog(config_path, main_menu_back_target="__main__")

    root = catalog.nodes["root"]
    section = catalog.nodes["section"]
    child = catalog.nodes["child"]
    assert catalog.main_menu_actions == {"Root": "root"}
    assert root.text == "Root text"
    assert [button.target_node_id for button in root.buttons] == ["section", None]
    assert root.buttons[1].url == "https://example.com"
    assert section.parent_node_id == "root"
    assert child.parent_node_id == "section"
    assert child.text == "Child text"
    assert child.photo_paths == (
        tmp_path / "media" / "child.png",
        tmp_path / "media" / "child-2.png",
    )
    assert child.section_node_id == "section"


def test_load_scenario_catalog_rejects_missing_child_node(tmp_path: Path) -> None:
    config_path = tmp_path / "menu.toml"
    config_path.write_text(
        """
main_menu = ["root"]

[nodes.root]
title = "Root"
children = ["missing"]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="referenced but not defined"):
        load_scenario_catalog(config_path, main_menu_back_target="__main__")
