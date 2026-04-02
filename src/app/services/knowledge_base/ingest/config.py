from __future__ import annotations

import logging
import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.services.knowledge_base.normalizer import normalize_cell_text, slugify
from app.services.knowledge_base.types import (
    FileOverride,
    ParseConfig,
    ParserProfile,
    SelectableSourceFormat,
    SourceOverride,
)

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
    source_formats = as_source_format_list(defaults.get("source_formats")) or ("csv", "xlsx")

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
        sheets_raw = _as_dict(override_map.get("sheets", {}))
        sheets = {
            str(sheet_name): _parse_source_override(_as_dict(sheet_override))
            for sheet_name, sheet_override in sheets_raw.items()
        }
        files[str(file_name)] = FileOverride(
            **asdict(_parse_source_override(override_map)),
            sheet_indexes=as_int_list(override_map.get("sheet_indexes")),
            sheets=sheets,
        )

    logger.info(
        "%s path=%s files=%s logical_id_overrides=%s",
        LOG_EVENT_CONFIG_LOADED,
        config_path.as_posix(),
        len(files),
        len(logical_id_overrides),
    )
    return ParseConfig(
        version=version,
        source_formats=source_formats,
        logical_id_overrides=logical_id_overrides,
        files=files,
    )


def resolve_file_override(config: ParseConfig, source_name: str) -> FileOverride:
    direct_match = config.files.get(source_name)
    if direct_match is not None:
        return direct_match

    folded_source_name = source_name.casefold()
    for file_name, override in config.files.items():
        if file_name.casefold() == folded_source_name:
            return override
    return FileOverride()


def resolve_source_override(
    config: ParseConfig,
    source_name: str,
    *,
    sheet_name: str | None = None,
) -> SourceOverride:
    file_override = resolve_file_override(config, source_name)
    if sheet_name is None:
        return file_override.merged_with(None)

    direct_match = file_override.sheets.get(sheet_name)
    if direct_match is not None:
        return file_override.merged_with(direct_match)

    folded_sheet_name = sheet_name.casefold()
    for configured_sheet_name, override in file_override.sheets.items():
        if configured_sheet_name.casefold() == folded_sheet_name:
            return file_override.merged_with(override)
    return file_override.merged_with(None)


def resolve_logical_id(config: ParseConfig, override: SourceOverride, source_slug: str) -> str:
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


def as_parser_profile(raw_value: object) -> ParserProfile | None:
    if raw_value is None:
        return None
    normalized = normalize_cell_text(str(raw_value)).casefold()
    if normalized in {"qa_table", "section_table", "column_split", "outline_sheet"}:
        return normalized  # type: ignore[return-value]
    return None


def as_legacy_split_mode(raw_value: object) -> ParserProfile | None:
    if raw_value is None:
        return None
    normalized = normalize_cell_text(str(raw_value)).casefold()
    if normalized == "column":
        return "column_split"
    return None


def as_str_list(raw_value: object) -> tuple[str, ...]:
    if not isinstance(raw_value, list):
        return ()

    values: list[str] = []
    for item in raw_value:
        normalized = normalize_cell_text(str(item))
        if normalized:
            values.append(normalized)
    return tuple(values)


def as_int_list(raw_value: object) -> tuple[int, ...]:
    if not isinstance(raw_value, list):
        return ()

    values: list[int] = []
    for item in raw_value:
        try:
            values.append(int(item))
        except (TypeError, ValueError):
            continue
    return tuple(values)


def as_bool(raw_value: object) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    return False


def as_source_format_list(raw_value: object) -> tuple[SelectableSourceFormat, ...]:
    if not isinstance(raw_value, list):
        return ()

    values: list[SelectableSourceFormat] = []
    for item in raw_value:
        normalized = normalize_cell_text(str(item)).casefold()
        if normalized in {"csv", "xlsx"} and normalized not in values:
            values.append(normalized)  # type: ignore[arg-type]
    return tuple(values)


def _parse_source_override(override_map: dict[str, Any]) -> SourceOverride:
    parser_profile = as_parser_profile(override_map.get("parser_profile"))
    if parser_profile is None:
        parser_profile = as_legacy_split_mode(override_map.get("split_mode"))

    return SourceOverride(
        parser_profile=parser_profile,
        title=as_optional_str(override_map.get("title")),
        category=as_optional_str(override_map.get("category")),
        logical_id=as_optional_str(override_map.get("logical_id")),
        split_column_name=as_optional_str(override_map.get("split_column_name")),
        section_column_name=as_optional_str(override_map.get("section_column_name")),
        question_column_name=as_optional_str(override_map.get("question_column_name")),
        answer_column_name=as_optional_str(override_map.get("answer_column_name")),
        content_ranges=as_str_list(override_map.get("content_ranges")),
        ignore_rows=as_int_list(override_map.get("ignore_rows")),
        ignore_columns=as_str_list(override_map.get("ignore_columns")),
        forced_header_rows=as_int_list(override_map.get("forced_header_rows")),
        forced_paragraph_rows=as_int_list(override_map.get("forced_paragraph_rows")),
        ignore=as_bool(override_map.get("ignore")),
    )


def _as_dict(raw_value: object) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        return raw_value
    return {}
