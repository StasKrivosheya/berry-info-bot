from __future__ import annotations

import json
import logging
from pathlib import Path

from app.services.knowledge_base.types_openai import ManifestSyncItem

logger = logging.getLogger(__name__)
LOG_EVENT_MANIFEST_LOADED = "kb_manifest_loaded"


def load_manifest_sync_items(manifest_path: Path) -> list[ManifestSyncItem]:
    """Read sync-ready manifest rows from parser output file."""

    if not manifest_path.exists():
        msg = f"Manifest file does not exist: {manifest_path.as_posix()}"
        raise FileNotFoundError(msg)

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        msg = "Manifest payload must include 'entries' list."
        raise ValueError(msg)

    output_dir = resolve_output_dir(
        manifest_path=manifest_path,
        raw_output_dir=payload.get("output_dir"),
    )
    items: list[ManifestSyncItem] = []
    for entry_index, entry in enumerate(entries, start=1):
        items.extend(
            _load_manifest_entry_items(
                entry=entry,
                entry_index=entry_index,
                output_dir=output_dir,
            )
        )

    items.sort(key=lambda item: (item.logical_id, item.markdown_relative_path.casefold()))
    logger.info(
        "%s manifest=%s output_dir=%s sync_item_count=%s",
        LOG_EVENT_MANIFEST_LOADED,
        manifest_path.as_posix(),
        output_dir.as_posix(),
        len(items),
    )
    return items


def resolve_output_dir(manifest_path: Path, raw_output_dir: object) -> Path:
    """Resolve output directory without depending on the current working directory."""

    if isinstance(raw_output_dir, str) and raw_output_dir.strip():
        output_dir = Path(raw_output_dir.strip())
        if output_dir.is_absolute():
            return output_dir.resolve()
        manifest_relative = (manifest_path.parent / output_dir).resolve()
        if manifest_relative.exists() or (manifest_relative / "markdown").exists():
            return manifest_relative

    return manifest_path.parent.resolve()


def _load_manifest_entry_items(
    *,
    entry: object,
    entry_index: int,
    output_dir: Path,
) -> list[ManifestSyncItem]:
    if not isinstance(entry, dict):
        msg = f"Manifest entry #{entry_index} must be an object."
        raise ValueError(msg)

    logical_id = _require_non_empty_str(entry, key="logical_id", entry_index=entry_index)
    category = _require_non_empty_str(entry, key="category", entry_index=entry_index)
    version = _require_non_empty_str(entry, key="version", entry_index=entry_index)
    updated_at_utc = str(entry.get("updated_at_utc", "")).strip()
    source_file = _resolve_source_file(entry)
    source_format = _resolve_source_format(entry, source_file)
    sheet_name = _optional_non_empty_str(entry.get("sheet_name"))
    workbook_file = _optional_non_empty_str(entry.get("workbook_file"))
    content_hash = str(entry.get("content_hash_sha256", "")).strip()
    output_md_files = entry.get("output_md_file")
    if not isinstance(output_md_files, list) or not output_md_files:
        msg = f"Manifest entry #{entry_index} must include a non-empty 'output_md_file' list."
        raise ValueError(msg)

    items: list[ManifestSyncItem] = []
    for file_index, markdown_relative_path in enumerate(output_md_files, start=1):
        relative_path = str(markdown_relative_path).strip()
        if not relative_path:
            msg = (
                f"Manifest entry #{entry_index} contains an empty path in "
                f"'output_md_file' at position {file_index}."
            )
            raise ValueError(msg)
        items.append(
            ManifestSyncItem(
                logical_id=logical_id,
                category=category,
                version=version,
                updated_at_utc=updated_at_utc,
                source_file=source_file,
                source_format=source_format,
                sheet_name=sheet_name,
                workbook_file=workbook_file,
                content_hash_sha256=content_hash,
                markdown_relative_path=relative_path,
                markdown_absolute_path=(output_dir / relative_path).resolve(),
            )
        )
    return items


def _resolve_source_file(entry: dict[str, object]) -> str:
    source_file = _optional_non_empty_str(entry.get("source_file"))
    if source_file:
        return source_file
    legacy_source_csv = _optional_non_empty_str(entry.get("source_csv"))
    if legacy_source_csv:
        return legacy_source_csv
    return ""


def _resolve_source_format(entry: dict[str, object], source_file: str) -> str:
    declared_format = _optional_non_empty_str(entry.get("source_format"))
    if declared_format:
        return declared_format
    if source_file.casefold().endswith(".xlsx"):
        return "xlsx"
    if source_file:
        return "csv"
    return "unknown"


def _optional_non_empty_str(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _require_non_empty_str(entry: dict[str, object], *, key: str, entry_index: int) -> str:
    value = str(entry.get(key, "")).strip()
    if value:
        return value

    msg = f"Manifest entry #{entry_index} must include a non-empty '{key}' value."
    raise ValueError(msg)

