from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from app.services.knowledge_base.csv_ingest import PreparedTable, read_and_prepare_csv
from app.services.knowledge_base.manifest_writer import write_manifest
from app.services.knowledge_base.markdown_render import render_documents
from app.services.knowledge_base.normalizer import compute_content_hash, prettify_title, slugify
from app.services.knowledge_base.parser_config import (
    load_parse_config as load_parse_config_impl,
)
from app.services.knowledge_base.parser_config import (
    resolve_file_override,
    resolve_logical_id,
)
from app.services.knowledge_base.types import (
    BatchParseResult,
    FileParseError,
    FileParseStats,
    ManifestEntry,
    ParseConfig,
)

logger = logging.getLogger(__name__)

MARKDOWN_DIRNAME = "markdown"
MANIFEST_FILENAME = "manifest.json"

LOG_EVENT_CSV_DISCOVERED = "kb_parser_csv_discovered"
LOG_EVENT_PARSE_MODE_SELECTED = "kb_parser_mode_selected"
LOG_EVENT_PARSE_MODE_FALLBACK = "kb_parser_mode_fallback"
LOG_EVENT_FILE_GENERATED = "kb_parser_file_generated"
LOG_EVENT_FILE_FAILED = "kb_parser_file_failed"


def parse_knowledge_base(
    input_dir: Path,
    output_dir: Path,
    config_path: Path | None = None,
) -> BatchParseResult:
    """Parse all CSV files and generate markdown plus a manifest."""

    config = load_parse_config(config_path)

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_dir = output_dir / MARKDOWN_DIRNAME
    markdown_dir.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(input_dir.glob("*.csv"), key=lambda path: path.name.casefold())
    for csv_file in csv_files:
        logger.info("%s source_csv=%s", LOG_EVENT_CSV_DISCOVERED, csv_file.name)

    entries: list[ManifestEntry] = []
    errors: list[FileParseError] = []
    stats: list[FileParseStats] = []

    for csv_file in csv_files:
        try:
            entry, file_stats = _parse_one_csv(csv_file, markdown_dir, config)
            entries.append(entry)
            stats.append(file_stats)
            logger.info(
                "%s source_csv=%s markdown_files=%s",
                LOG_EVENT_FILE_GENERATED,
                csv_file.name,
                file_stats.markdown_file_count,
            )
        except Exception as exc:
            errors.append(
                FileParseError(
                    source_csv=csv_file.name,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            )
            logger.exception("%s source_csv=%s", LOG_EVENT_FILE_FAILED, csv_file.name)

    if not csv_files:
        errors.append(
            FileParseError(
                source_csv="*",
                error_type="NoCsvFilesFound",
                message=f"No CSV files discovered in '{input_dir.as_posix()}'.",
            )
        )

    manifest_path = output_dir / MANIFEST_FILENAME
    write_manifest(
        manifest_path=manifest_path,
        input_dir=input_dir,
        output_dir=output_dir,
        entries=entries,
        errors=errors,
    )

    return BatchParseResult(
        entries=entries,
        errors=errors,
        stats=stats,
        discovered_file_count=len(csv_files),
        manifest_path=manifest_path,
    )


def load_parse_config(config_path: Path | None) -> ParseConfig:
    """Compatibility wrapper around dedicated parse config loader."""

    return load_parse_config_impl(config_path)


def _parse_one_csv(
    csv_path: Path,
    markdown_dir: Path,
    config: ParseConfig,
) -> tuple[ManifestEntry, FileParseStats]:
    prepared_table = read_and_prepare_csv(csv_path)
    _validate_non_empty_table(prepared_table, csv_path.name)

    source_slug = slugify(csv_path.stem)
    override = resolve_file_override(config, csv_path.name)
    title = override.title or prettify_title(csv_path.stem)
    category = override.category or csv_path.stem
    logical_id = resolve_logical_id(config, override, source_slug)

    parse_mode, docs = render_documents(
        rows=prepared_table.rows,
        source_slug=source_slug,
        title=title,
        override=override,
    )
    logger.info(
        "%s source_csv=%s mode=%s",
        LOG_EVENT_PARSE_MODE_SELECTED,
        csv_path.name,
        parse_mode,
    )
    if parse_mode == "fallback":
        logger.warning(
            "%s source_csv=%s note=parser_used_conservative_fallback_rendering",
            LOG_EVENT_PARSE_MODE_FALLBACK,
            csv_path.name,
        )

    _cleanup_previous_outputs(markdown_dir=markdown_dir, source_slug=source_slug)
    docs = sorted(docs, key=lambda doc: doc.file_name.casefold())
    for document in docs:
        (markdown_dir / document.file_name).write_text(document.content, encoding="utf-8")

    output_files = [f"{MARKDOWN_DIRNAME}/{document.file_name}" for document in docs]
    content_hash = compute_content_hash([document.content for document in docs])
    updated_at_utc = datetime.now(tz=UTC).isoformat()

    entry = ManifestEntry(
        source_csv=csv_path.name,
        output_md_file=output_files,
        logical_id=logical_id,
        category=category,
        version=config.version,
        updated_at_utc=updated_at_utc,
        row_count=prepared_table.row_count,
        non_empty_cell_count=prepared_table.non_empty_cell_count,
        content_hash_sha256=content_hash,
    )
    stats = FileParseStats(
        source_csv=csv_path.name,
        parse_mode=parse_mode,
        markdown_file_count=len(output_files),
        row_count=prepared_table.row_count,
        non_empty_cell_count=prepared_table.non_empty_cell_count,
    )
    return entry, stats


def _validate_non_empty_table(table: PreparedTable, source_csv_name: str) -> None:
    if table.rows:
        return
    msg = f"CSV '{source_csv_name}' has no non-empty rows after normalization."
    raise ValueError(msg)


def _cleanup_previous_outputs(markdown_dir: Path, source_slug: str) -> None:
    exact_file = markdown_dir / f"{source_slug}.md"
    if exact_file.exists():
        exact_file.unlink()
    for existing_file in markdown_dir.glob(f"{source_slug}--*.md"):
        existing_file.unlink()
