from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from app.services.knowledge_base.normalizer import normalize_cell_text, slugify
from app.services.knowledge_base.types import FileOverride, ParseConfig

logger = logging.getLogger(__name__)

DEFAULT_VERSION = "1.0"
LOG_EVENT_CONFIG_LOADED = "kb_parser_config_loaded"


def load_parse_config(config_path: Path | None) -> ParseConfig:
    """Load parse configuration from TOML file, or return defaults."""

    if config_path is None:
        return ParseConfig(version=DEFAULT_VERSION)

    if not config_path.exists():
        logger.warning("kb_parser_config_missing path=%s; using defaults", config_path.as_posix())
        return ParseConfig(version=DEFAULT_VERSION)

    raw_data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    defaults = _as_dict(raw_data.get("defaults", {}))
    version = str(defaults.get("version", DEFAULT_VERSION))

    logical_id_overrides_raw = _as_dict(raw_data.get("logical_id_overrides", {}))
    logical_id_overrides: dict[str, str] = {}
    for key, raw_value in logical_id_overrides_raw.items():
        mapped_value = normalize_cell_text(str(raw_value))
        if not mapped_value:
            continue
        logical_id_overrides[slugify(str(key))] = mapped_value

    files_raw = _as_dict(raw_data.get("files", {}))
    files: dict[str, FileOverride] = {}
    for file_name, raw_override in files_raw.items():
        override_map = _as_dict(raw_override)
        files[str(file_name)] = FileOverride(
            title=_as_optional_str(override_map.get("title")),
            category=_as_optional_str(override_map.get("category")),
            logical_id=_as_optional_str(override_map.get("logical_id")),
            split_mode=_as_split_mode(override_map.get("split_mode")),
            split_column_name=_as_optional_str(override_map.get("split_column_name")),
            section_column_name=_as_optional_str(override_map.get("section_column_name")),
            question_column_name=_as_optional_str(override_map.get("question_column_name")),
            answer_column_name=_as_optional_str(override_map.get("answer_column_name")),
        )

    logger.info(
        "%s path=%s files=%s logical_id_overrides=%s",
        LOG_EVENT_CONFIG_LOADED,
        config_path.as_posix(),
        len(files),
        len(logical_id_overrides),
    )
    return ParseConfig(version=version, logical_id_overrides=logical_id_overrides, files=files)


def resolve_file_override(config: ParseConfig, source_name: str) -> FileOverride:
    direct_match = config.files.get(source_name)
    if direct_match is not None:
        return direct_match

    folded_source_name = source_name.casefold()
    for file_name, override in config.files.items():
        if file_name.casefold() == folded_source_name:
            return override
    return FileOverride()


def resolve_logical_id(config: ParseConfig, override: FileOverride, source_slug: str) -> str:
    if override.logical_id:
        return override.logical_id
    if source_slug in config.logical_id_overrides:
        return config.logical_id_overrides[source_slug]
    return source_slug


def as_optional_str(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    normalized = normalize_cell_text(str(raw_value))
    return normalized or None


def as_split_mode(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    normalized = normalize_cell_text(str(raw_value)).casefold()
    if normalized in {"single", "column"}:
        return normalized
    return None


def _as_optional_str(raw_value: object) -> str | None:
    return as_optional_str(raw_value)


def _as_split_mode(raw_value: object) -> str | None:
    return as_split_mode(raw_value)


def _as_dict(raw_value: object) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        return raw_value
    return {}

