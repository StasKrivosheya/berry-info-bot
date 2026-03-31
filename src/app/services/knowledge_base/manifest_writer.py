from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.services.knowledge_base.types import FileParseError, ManifestEntry

logger = logging.getLogger(__name__)
LOG_EVENT_MANIFEST_WRITTEN = "kb_parser_manifest_written"


def write_manifest(
    *,
    manifest_path: Path,
    input_dir: Path,
    output_dir: Path,
    entries: list[ManifestEntry],
    errors: list[FileParseError],
) -> None:
    """Persist parser manifest in deterministic JSON layout."""

    payload = {
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "source_dir": input_dir.as_posix(),
        "output_dir": output_dir.as_posix(),
        "entries": [entry.to_dict() for entry in entries],
        "errors": [error.to_dict() for error in errors],
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.info(
        "%s path=%s entries=%s errors=%s",
        LOG_EVENT_MANIFEST_WRITTEN,
        manifest_path.as_posix(),
        len(entries),
        len(errors),
    )

