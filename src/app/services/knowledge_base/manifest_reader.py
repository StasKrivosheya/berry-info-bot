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
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        logical_id = str(entry.get("logical_id", "")).strip()
        category = str(entry.get("category", "")).strip()
        version = str(entry.get("version", "")).strip()
        updated_at_utc = str(entry.get("updated_at_utc", "")).strip()
        source_csv = str(entry.get("source_csv", "")).strip()
        content_hash = str(entry.get("content_hash_sha256", "")).strip()
        output_md_files = entry.get("output_md_file")

        if not logical_id or not category or not version or not output_md_files:
            continue
        if not isinstance(output_md_files, list):
            continue

        for markdown_relative_path in output_md_files:
            relative_path = str(markdown_relative_path).strip()
            if not relative_path:
                continue
            items.append(
                ManifestSyncItem(
                    logical_id=logical_id,
                    category=category,
                    version=version,
                    updated_at_utc=updated_at_utc,
                    source_csv=source_csv,
                    content_hash_sha256=content_hash,
                    markdown_relative_path=relative_path,
                    markdown_absolute_path=(output_dir / relative_path).resolve(),
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
    """Resolve output directory from manifest metadata and runtime cwd."""

    if isinstance(raw_output_dir, str) and raw_output_dir.strip():
        output_dir = Path(raw_output_dir.strip())
        if output_dir.is_absolute():
            return output_dir

        cwd_candidate = (Path.cwd() / output_dir).resolve()
        if cwd_candidate.exists():
            return cwd_candidate

        return (manifest_path.parent / output_dir).resolve()

    return manifest_path.parent.resolve()

