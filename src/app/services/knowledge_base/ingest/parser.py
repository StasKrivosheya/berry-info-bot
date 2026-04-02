from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from app.services.knowledge_base.ingest.config import (
    load_parse_config as load_parse_config_impl,
)
from app.services.knowledge_base.ingest.config import (
    resolve_file_override,
    resolve_logical_id,
    resolve_source_override,
)
from app.services.knowledge_base.ingest.csv import PreparedTable, read_and_prepare_csv
from app.services.knowledge_base.ingest.markdown import render_documents
from app.services.knowledge_base.ingest.outline import OutlineParseError, render_outline_sheet
from app.services.knowledge_base.ingest.xlsx import (
    PreparedWorkbookSheet,
    build_table_from_sheet,
    load_visible_workbook_sheets,
)
from app.services.knowledge_base.manifest.writer import write_manifest
from app.services.knowledge_base.normalizer import (
    compute_content_hash,
    legacy_ascii_slugify,
    prettify_title,
    slugify,
)
from app.services.knowledge_base.types import (
    BatchParseResult,
    FileParseError,
    FileParseStats,
    ManifestEntry,
    ParseConfig,
    ParseDiagnostic,
    SelectableSourceFormat,
    SourceFormat,
    SourceOverride,
)

logger = logging.getLogger(__name__)

MARKDOWN_DIRNAME = "markdown"
MANIFEST_FILENAME = "manifest.json"

LOG_EVENT_SOURCE_DISCOVERED = "kb_parser_source_discovered"
LOG_EVENT_PARSE_MODE_SELECTED = "kb_parser_mode_selected"
LOG_EVENT_PARSE_MODE_FALLBACK = "kb_parser_mode_fallback"
LOG_EVENT_FILE_GENERATED = "kb_parser_file_generated"
LOG_EVENT_FILE_FAILED = "kb_parser_file_failed"


def parse_knowledge_base(
    input_dir: Path,
    output_dir: Path,
    config_path: Path | None = None,
    source_formats: tuple[SelectableSourceFormat, ...] | None = None,
) -> BatchParseResult:
    """Parse CSV and XLSX sources into markdown plus a manifest."""

    config = load_parse_config(config_path)
    allowed_source_formats = source_formats or config.source_formats

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_dir = output_dir / MARKDOWN_DIRNAME
    markdown_dir.mkdir(parents=True, exist_ok=True)

    input_sources = sorted(
        [*input_dir.glob("*.csv"), *input_dir.glob("*.xlsx")],
        key=lambda path: path.name.casefold(),
    )
    entries: list[ManifestEntry] = []
    errors: list[FileParseError] = []
    stats: list[FileParseStats] = []
    discovered_source_count = 0
    eligible_source_found = False

    for source_path in input_sources:
        source_format = _detect_source_format(source_path)
        if source_format not in allowed_source_formats:
            continue
        eligible_source_found = True

        file_override = resolve_file_override(config, source_path.name)
        if file_override.ignore:
            continue

        if source_format == "csv":
            override = resolve_source_override(config, source_path.name)
            discovered_source_count += 1
            logger.info(
                "%s source=%s format=%s",
                LOG_EVENT_SOURCE_DISCOVERED,
                source_path.name,
                source_format,
            )
            try:
                entry, file_stats = _parse_csv_source(source_path, markdown_dir, config, override)
                entries.append(entry)
                stats.append(file_stats)
                logger.info(
                    "%s source=%s markdown_files=%s",
                    LOG_EVENT_FILE_GENERATED,
                    file_stats.source_ref,
                    file_stats.markdown_file_count,
                )
            except Exception as exc:
                error = _build_parse_error(
                    source_file=source_path.name,
                    source_format=source_format,
                    sheet_name=None,
                    sheet_index=None,
                    workbook_file=None,
                    exc=exc,
                )
                errors.append(error)
                logger.exception("%s source=%s", LOG_EVENT_FILE_FAILED, error.source_ref)
            continue

        try:
            workbook_sheets = load_visible_workbook_sheets(source_path)
        except Exception as exc:
            discovered_source_count += 1
            error = _build_parse_error(
                source_file=source_path.name,
                source_format="xlsx",
                sheet_name=None,
                sheet_index=None,
                workbook_file=source_path.name,
                exc=exc,
            )
            errors.append(error)
            logger.exception("%s source=%s", LOG_EVENT_FILE_FAILED, error.source_ref)
            continue

        try:
            workbook_sheets = _filter_workbook_sheets(workbook_sheets, file_override.sheet_indexes)
        except Exception as exc:
            discovered_source_count += 1
            error = _build_parse_error(
                source_file=source_path.name,
                source_format="xlsx",
                sheet_name=None,
                sheet_index=None,
                workbook_file=source_path.name,
                exc=exc,
            )
            errors.append(error)
            logger.exception("%s source=%s", LOG_EVENT_FILE_FAILED, error.source_ref)
            continue

        if not workbook_sheets:
            discovered_source_count += 1
            error = FileParseError(
                source_file=source_path.name,
                source_format="xlsx",
                sheet_name=None,
                sheet_index=None,
                workbook_file=source_path.name,
                error_type="NoSelectedSheetsFound",
                message=(
                    f"Workbook '{source_path.name}' has no visible worksheets matching the "
                    "configured selection."
                ),
            )
            errors.append(error)
            logger.error("%s source=%s", LOG_EVENT_FILE_FAILED, error.source_ref)
            continue

        for sheet in workbook_sheets:
            override = resolve_source_override(
                config,
                source_path.name,
                sheet_name=sheet.sheet_name,
            )
            if override.ignore:
                continue
            discovered_source_count += 1
            logger.info(
                "%s source=%s format=%s",
                LOG_EVENT_SOURCE_DISCOVERED,
                _source_ref(source_path.name, sheet.sheet_name),
                "xlsx",
            )
            try:
                entry, file_stats = _parse_xlsx_sheet(
                    workbook_path=source_path,
                    sheet=sheet,
                    markdown_dir=markdown_dir,
                    config=config,
                    override=override,
                )
                entries.append(entry)
                stats.append(file_stats)
                logger.info(
                    "%s source=%s markdown_files=%s",
                    LOG_EVENT_FILE_GENERATED,
                    file_stats.source_ref,
                    file_stats.markdown_file_count,
                )
            except Exception as exc:
                error = _build_parse_error(
                    source_file=source_path.name,
                    source_format="xlsx",
                    sheet_name=sheet.sheet_name,
                    sheet_index=sheet.sheet_index,
                    workbook_file=source_path.name,
                    exc=exc,
                )
                errors.append(error)
                logger.exception("%s source=%s", LOG_EVENT_FILE_FAILED, error.source_ref)

    if not input_sources:
        errors.append(
            FileParseError(
                source_file="*",
                source_format="unknown",
                sheet_name=None,
                sheet_index=None,
                workbook_file=None,
                error_type="NoSourceFilesFound",
                message=(
                    "No source files discovered. Place CSV or XLSX exports in "
                    f"'{input_dir.as_posix()}'."
                ),
            )
        )
    elif not eligible_source_found:
        errors.append(
            FileParseError(
                source_file="*",
                source_format="unknown",
                sheet_name=None,
                sheet_index=None,
                workbook_file=None,
                error_type="NoMatchingSourceFormatsFound",
                message=(
                    "No source files matched the selected source formats: "
                    f"{', '.join(sorted(allowed_source_formats))}."
                ),
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
        discovered_source_count=discovered_source_count,
        manifest_path=manifest_path,
    )


def load_parse_config(config_path: Path | None) -> ParseConfig:
    """Compatibility wrapper around dedicated parse config loader."""

    return load_parse_config_impl(config_path)


def _parse_csv_source(
    csv_path: Path,
    markdown_dir: Path,
    config: ParseConfig,
    override: SourceOverride,
) -> tuple[ManifestEntry, FileParseStats]:
    source_slug = slugify(csv_path.stem)
    cleanup_source_slugs = _build_cleanup_source_slugs(source_slug, csv_path.stem)
    _cleanup_previous_outputs(
        markdown_dir=markdown_dir,
        source_slugs=(source_slug, *cleanup_source_slugs),
    )
    prepared_table = read_and_prepare_csv(csv_path)
    _validate_non_empty_table(prepared_table, _source_ref(csv_path.name, None))

    title = override.title or prettify_title(csv_path.stem)
    category = override.category or csv_path.stem
    logical_id = resolve_logical_id(config, override, source_slug)
    parse_mode, docs = render_documents(
        rows=prepared_table.rows,
        source_slug=source_slug,
        title=title,
        override=override,
        infer_headers_in_fallback=False,
    )
    _log_parse_mode(parse_mode=parse_mode, source_file=csv_path.name, sheet_name=None)
    return _finalize_parse_result(
        markdown_dir=markdown_dir,
        source_slug=source_slug,
        docs=docs,
        source_file=csv_path.name,
        source_format="csv",
        sheet_name=None,
        sheet_index=None,
        workbook_file=None,
        logical_id=logical_id,
        category=category,
        version=config.version,
        row_count=prepared_table.row_count,
        non_empty_cell_count=prepared_table.non_empty_cell_count,
        parse_mode=parse_mode,
        cleanup_source_slugs=cleanup_source_slugs,
    )


def _parse_xlsx_sheet(
    *,
    workbook_path: Path,
    sheet: PreparedWorkbookSheet,
    markdown_dir: Path,
    config: ParseConfig,
    override: SourceOverride,
) -> tuple[ManifestEntry, FileParseStats]:
    source_key = f"{workbook_path.stem}-{sheet.sheet_name}"
    source_slug = slugify(source_key)
    cleanup_source_slugs = _build_cleanup_source_slugs(source_slug, source_key)
    _cleanup_previous_outputs(
        markdown_dir=markdown_dir,
        source_slugs=(source_slug, *cleanup_source_slugs),
    )
    title = override.title or prettify_title(sheet.sheet_name)
    category = override.category or sheet.sheet_name
    logical_id = resolve_logical_id(config, override, source_slug)

    parse_mode = override.parser_profile or "outline_sheet"
    if parse_mode == "outline_sheet":
        parse_mode, docs, row_count, non_empty_cell_count = render_outline_sheet(
            sheet=sheet,
            source_slug=source_slug,
            default_title=title,
            override=override,
        )
    else:
        prepared_table = build_table_from_sheet(sheet, override)
        _validate_non_empty_table(prepared_table, _source_ref(workbook_path.name, sheet.sheet_name))
        parse_mode, docs = render_documents(
            rows=prepared_table.rows,
            source_slug=source_slug,
            title=title,
            override=override,
            infer_headers_in_fallback=False,
        )
        row_count = prepared_table.row_count
        non_empty_cell_count = prepared_table.non_empty_cell_count

    _log_parse_mode(
        parse_mode=parse_mode,
        source_file=workbook_path.name,
        sheet_name=sheet.sheet_name,
    )
    return _finalize_parse_result(
        markdown_dir=markdown_dir,
        source_slug=source_slug,
        docs=docs,
        source_file=workbook_path.name,
        source_format="xlsx",
        sheet_name=sheet.sheet_name,
        sheet_index=sheet.sheet_index,
        workbook_file=workbook_path.name,
        logical_id=logical_id,
        category=category,
        version=config.version,
        row_count=row_count,
        non_empty_cell_count=non_empty_cell_count,
        parse_mode=parse_mode,
        cleanup_source_slugs=cleanup_source_slugs,
    )


def _finalize_parse_result(
    *,
    markdown_dir: Path,
    source_slug: str,
    docs,
    source_file: str,
    source_format: SourceFormat,
    sheet_name: str | None,
    sheet_index: int | None,
    workbook_file: str | None,
    logical_id: str,
    category: str,
    version: str,
    row_count: int,
    non_empty_cell_count: int,
    parse_mode: str,
    cleanup_source_slugs: tuple[str, ...] = (),
) -> tuple[ManifestEntry, FileParseStats]:
    docs = sorted(docs, key=lambda doc: doc.file_name.casefold())
    for document in docs:
        (markdown_dir / document.file_name).write_text(document.content, encoding="utf-8")

    output_files = [f"{MARKDOWN_DIRNAME}/{document.file_name}" for document in docs]
    content_hash = compute_content_hash([document.content for document in docs])
    updated_at_utc = datetime.now(tz=UTC).isoformat()

    entry = ManifestEntry(
        source_file=source_file,
        source_format=source_format,
        sheet_name=sheet_name,
        sheet_index=sheet_index,
        workbook_file=workbook_file,
        output_md_file=output_files,
        logical_id=logical_id,
        category=category,
        version=version,
        updated_at_utc=updated_at_utc,
        row_count=row_count,
        non_empty_cell_count=non_empty_cell_count,
        content_hash_sha256=content_hash,
    )
    stats = FileParseStats(
        source_file=source_file,
        source_format=source_format,
        sheet_name=sheet_name,
        sheet_index=sheet_index,
        workbook_file=workbook_file,
        parse_mode=parse_mode,
        markdown_file_count=len(output_files),
        row_count=row_count,
        non_empty_cell_count=non_empty_cell_count,
    )
    return entry, stats


def _validate_non_empty_table(table: PreparedTable, source_ref: str) -> None:
    if table.rows:
        return
    msg = f"Source '{source_ref}' has no non-empty rows after normalization."
    raise ValueError(msg)


def _cleanup_previous_outputs(markdown_dir: Path, source_slugs: tuple[str, ...]) -> None:
    for source_slug in dict.fromkeys(source_slugs):
        exact_file = markdown_dir / f"{source_slug}.md"
        if exact_file.exists():
            exact_file.unlink()
        for existing_file in markdown_dir.glob(f"{source_slug}--*.md"):
            existing_file.unlink()


def _detect_source_format(source_path: Path) -> SourceFormat:
    if source_path.suffix.casefold() == ".xlsx":
        return "xlsx"
    return "csv"


def _filter_workbook_sheets(
    workbook_sheets: list[PreparedWorkbookSheet],
    selected_indexes: tuple[int, ...],
) -> list[PreparedWorkbookSheet]:
    if not selected_indexes:
        return workbook_sheets

    available_indexes = {sheet.sheet_index for sheet in workbook_sheets}
    invalid_indexes = sorted(
        index for index in dict.fromkeys(selected_indexes) if index not in available_indexes
    )
    if invalid_indexes:
        available_display = ", ".join(str(index) for index in sorted(available_indexes)) or "none"
        invalid_display = ", ".join(str(index) for index in invalid_indexes)
        msg = (
            "Configured sheet_indexes contain indexes that are not present among visible sheets: "
            f"{invalid_display}. Available visible sheet indexes: {available_display}."
        )
        raise ValueError(msg)

    selected_index_set = set(selected_indexes)
    return [sheet for sheet in workbook_sheets if sheet.sheet_index in selected_index_set]


def _build_cleanup_source_slugs(source_slug: str, source_key: str) -> tuple[str, ...]:
    legacy_slug = legacy_ascii_slugify(source_key)
    if legacy_slug == source_slug:
        return ()
    return (legacy_slug,)


def _source_ref(source_file: str, sheet_name: str | None) -> str:
    if sheet_name:
        return f"{source_file}#{sheet_name}"
    return source_file


def _log_parse_mode(*, parse_mode: str, source_file: str, sheet_name: str | None) -> None:
    source_ref = _source_ref(source_file, sheet_name)
    logger.info("%s source=%s mode=%s", LOG_EVENT_PARSE_MODE_SELECTED, source_ref, parse_mode)
    if parse_mode == "fallback":
        logger.warning(
            "%s source=%s note=parser_used_plain_text_fallback_rendering",
            LOG_EVENT_PARSE_MODE_FALLBACK,
            source_ref,
        )


def _build_parse_error(
    *,
    source_file: str,
    source_format: SourceFormat,
    sheet_name: str | None,
    sheet_index: int | None,
    workbook_file: str | None,
    exc: Exception,
) -> FileParseError:
    diagnostics: list[ParseDiagnostic] = []
    if isinstance(exc, OutlineParseError):
        diagnostics = exc.diagnostics
    return FileParseError(
        source_file=source_file,
        source_format=source_format,
        sheet_name=sheet_name,
        sheet_index=sheet_index,
        workbook_file=workbook_file,
        error_type=type(exc).__name__,
        message=str(exc),
        diagnostics=diagnostics,
    )

