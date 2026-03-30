from __future__ import annotations

import csv
import io
import json
import logging
import tomllib
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.knowledge_base.normalizer import (
    compute_content_hash,
    normalize_cell_text,
    normalize_header_name,
    prettify_title,
    slugify,
    split_labelled_cell,
)
from app.services.knowledge_base.types import (
    BatchParseResult,
    FileOverride,
    FileParseError,
    FileParseStats,
    ManifestEntry,
    ParseConfig,
)

logger = logging.getLogger(__name__)

DEFAULT_VERSION = "1.0"
DEFAULT_SPLIT_MODE = "single"
MARKDOWN_DIRNAME = "markdown"
MANIFEST_FILENAME = "manifest.json"
SUPPORTED_ENCODINGS = ("utf-8-sig", "cp1251")

LOG_EVENT_CONFIG_LOADED = "kb_parser_config_loaded"
LOG_EVENT_CSV_DISCOVERED = "kb_parser_csv_discovered"
LOG_EVENT_PARSE_MODE_SELECTED = "kb_parser_mode_selected"
LOG_EVENT_FILE_GENERATED = "kb_parser_file_generated"
LOG_EVENT_FILE_FAILED = "kb_parser_file_failed"
LOG_EVENT_MANIFEST_WRITTEN = "kb_parser_manifest_written"


@dataclass(slots=True)
class _RenderedMarkdown:
    file_name: str
    content: str


@dataclass(slots=True)
class _PreparedTable:
    rows: list[list[str]]
    row_count: int
    non_empty_cell_count: int


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
            error = FileParseError(
                source_csv=csv_file.name,
                error_type=type(exc).__name__,
                message=str(exc),
            )
            errors.append(error)
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
    _write_manifest(
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


def _parse_one_csv(
    csv_path: Path,
    markdown_dir: Path,
    config: ParseConfig,
) -> tuple[ManifestEntry, FileParseStats]:
    prepared_table = _read_and_prepare_csv(csv_path)
    if not prepared_table.rows:
        msg = f"CSV '{csv_path.name}' has no non-empty rows after normalization."
        raise ValueError(msg)

    source_slug = slugify(csv_path.stem)
    file_override = _resolve_file_override(config, csv_path.name)
    title = file_override.title or prettify_title(csv_path.stem)
    category = file_override.category or csv_path.stem
    logical_id = _resolve_logical_id(config, file_override, source_slug)
    parse_mode, docs = _render_documents(
        rows=prepared_table.rows,
        source_slug=source_slug,
        title=title,
        override=file_override,
    )

    logger.info(
        "%s source_csv=%s mode=%s",
        LOG_EVENT_PARSE_MODE_SELECTED,
        csv_path.name,
        parse_mode,
    )

    _cleanup_previous_outputs(markdown_dir=markdown_dir, source_slug=source_slug)
    docs = sorted(docs, key=lambda doc: doc.file_name.casefold())

    for document in docs:
        target_path = markdown_dir / document.file_name
        target_path.write_text(document.content, encoding="utf-8")

    output_files = [f"{MARKDOWN_DIRNAME}/{document.file_name}" for document in docs]
    content_hash = compute_content_hash([document.content for document in docs])
    updated_at_utc = datetime.now(tz=UTC).isoformat()

    manifest_entry = ManifestEntry(
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
    file_stats = FileParseStats(
        source_csv=csv_path.name,
        parse_mode=parse_mode,
        markdown_file_count=len(output_files),
        row_count=prepared_table.row_count,
        non_empty_cell_count=prepared_table.non_empty_cell_count,
    )
    return manifest_entry, file_stats


def _render_documents(
    rows: list[list[str]],
    source_slug: str,
    title: str,
    override: FileOverride,
) -> tuple[str, list[_RenderedMarkdown]]:
    header_map = _build_header_map(rows[0])

    qa_mode = _resolve_qa_mode(override, header_map)
    if qa_mode is not None:
        body = _render_qa_body(
            headers=rows[0],
            data_rows=rows[1:],
            question_index=qa_mode["question_index"],
            answer_index=qa_mode["answer_index"],
            section_index=qa_mode.get("section_index"),
        )
        docs = [
            _RenderedMarkdown(
                file_name=f"{source_slug}.md",
                content=_compose_document(title, body),
            )
        ]
        return "qa", docs

    section_mode = _resolve_section_mode(override, header_map)
    if section_mode is not None:
        body = _render_section_body(
            headers=rows[0],
            data_rows=rows[1:],
            section_index=section_mode["section_index"],
        )
        docs = [
            _RenderedMarkdown(
                file_name=f"{source_slug}.md",
                content=_compose_document(title, body),
            )
        ]
        return "section", docs

    split_mode = _resolve_split_mode(override, header_map)
    if split_mode is not None:
        docs = _render_split_documents(
            source_slug=source_slug,
            title=title,
            headers=rows[0],
            data_rows=rows[1:],
            split_index=split_mode["split_index"],
        )
        return "column_split", docs

    inferred_headers, data_rows = _infer_fallback_headers(rows)
    body = _render_fallback_body(headers=inferred_headers, data_rows=data_rows)
    docs = [
        _RenderedMarkdown(
            file_name=f"{source_slug}.md",
            content=_compose_document(title, body),
        )
    ]
    return "fallback", docs


def _resolve_qa_mode(override: FileOverride, header_map: dict[str, int]) -> dict[str, int] | None:
    if not override.question_column_name or not override.answer_column_name:
        return None

    question_index = _resolve_column_index(header_map, override.question_column_name)
    answer_index = _resolve_column_index(header_map, override.answer_column_name)
    if question_index is None or answer_index is None:
        return None

    payload: dict[str, int] = {
        "question_index": question_index,
        "answer_index": answer_index,
    }
    if override.section_column_name:
        section_index = _resolve_column_index(header_map, override.section_column_name)
        if section_index is not None:
            payload["section_index"] = section_index
    return payload


def _resolve_section_mode(
    override: FileOverride,
    header_map: dict[str, int],
) -> dict[str, int] | None:
    if not override.section_column_name:
        return None

    section_index = _resolve_column_index(header_map, override.section_column_name)
    if section_index is None:
        return None
    return {"section_index": section_index}


def _resolve_split_mode(
    override: FileOverride,
    header_map: dict[str, int],
) -> dict[str, int] | None:
    split_mode = (override.split_mode or DEFAULT_SPLIT_MODE).casefold()
    if split_mode != "column" or not override.split_column_name:
        return None

    split_index = _resolve_column_index(header_map, override.split_column_name)
    if split_index is None:
        return None
    return {"split_index": split_index}


def _read_and_prepare_csv(csv_path: Path) -> _PreparedTable:
    csv_bytes = csv_path.read_bytes()
    csv_text = _decode_csv_bytes(csv_bytes)

    reader = csv.reader(io.StringIO(csv_text, newline=""), strict=True)
    normalized_rows = [[normalize_cell_text(cell) for cell in row] for row in reader]
    non_empty_rows = [row for row in normalized_rows if any(cell for cell in row)]
    trimmed_rows = _trim_empty_columns(non_empty_rows)

    row_count = len(trimmed_rows)
    non_empty_cell_count = sum(1 for row in trimmed_rows for cell in row if cell)
    return _PreparedTable(
        rows=trimmed_rows,
        row_count=row_count,
        non_empty_cell_count=non_empty_cell_count,
    )


def _decode_csv_bytes(csv_bytes: bytes) -> str:
    decode_error: UnicodeDecodeError | None = None
    for encoding in SUPPORTED_ENCODINGS:
        try:
            return csv_bytes.decode(encoding)
        except UnicodeDecodeError as exc:
            decode_error = exc
    if decode_error is None:
        msg = "Failed to decode CSV bytes with configured encodings."
        raise ValueError(msg)
    raise decode_error


def _trim_empty_columns(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return []

    max_columns = max(len(row) for row in rows)
    padded_rows = [row + [""] * (max_columns - len(row)) for row in rows]
    non_empty_indexes = [
        index for index in range(max_columns) if any(row[index] for row in padded_rows)
    ]
    return [[row[index] for index in non_empty_indexes] for row in padded_rows]


def _infer_fallback_headers(rows: list[list[str]]) -> tuple[list[str] | None, list[list[str]]]:
    if len(rows) < 2:
        return None, rows

    first_row = rows[0]
    non_empty_headers = [cell for cell in first_row if cell]
    if len(non_empty_headers) < 2:
        return None, rows

    header_keys = [normalize_header_name(cell) for cell in non_empty_headers]
    if len(set(header_keys)) != len(header_keys):
        return None, rows

    if any(len(cell) > 60 for cell in non_empty_headers):
        return None, rows

    return first_row, rows[1:]


def _render_qa_body(
    headers: list[str],
    data_rows: list[list[str]],
    question_index: int,
    answer_index: int,
    section_index: int | None = None,
) -> str:
    groups: OrderedDict[str, list[list[str]]] = OrderedDict()
    for row in data_rows:
        question = _cell(row, question_index)
        answer = _cell(row, answer_index)
        if not question and not answer:
            continue
        section_name = "General"
        if section_index is not None:
            section_name = _cell(row, section_index) or "General"
        groups.setdefault(section_name, []).append(row)

    body_chunks: list[str] = []
    include_sections = section_index is not None or len(groups) > 1
    for section_name, rows_in_section in groups.items():
        section_chunks: list[str] = []
        if include_sections:
            section_chunks.append(f"## {section_name}")
        for row in rows_in_section:
            question = _cell(row, question_index) or "Question"
            answer = _cell(row, answer_index)
            extra = _render_row(
                row=row,
                headers=headers,
                skip_indexes={
                    question_index,
                    answer_index,
                    section_index if section_index is not None else -1,
                },
            )
            block_parts = [f"### {question}"]
            if answer:
                block_parts.append(answer)
            if extra:
                block_parts.append(extra)
            section_chunks.append("\n\n".join(block_parts))
        body_chunks.append("\n\n".join(section_chunks))
    return "\n\n".join(body_chunks)


def _render_section_body(headers: list[str], data_rows: list[list[str]], section_index: int) -> str:
    groups: OrderedDict[str, list[list[str]]] = OrderedDict()
    for row in data_rows:
        section_name = _cell(row, section_index) or "General"
        groups.setdefault(section_name, []).append(row)

    chunks: list[str] = []
    for section_name, rows_in_section in groups.items():
        section_rows: list[str] = []
        for row in rows_in_section:
            rendered_row = _render_row(row=row, headers=headers, skip_indexes={section_index})
            if rendered_row:
                section_rows.append(rendered_row)
        if not section_rows:
            continue
        chunks.append(f"## {section_name}\n\n" + "\n\n".join(section_rows))
    return "\n\n".join(chunks)


def _render_split_documents(
    source_slug: str,
    title: str,
    headers: list[str],
    data_rows: list[list[str]],
    split_index: int,
) -> list[_RenderedMarkdown]:
    grouped_rows: OrderedDict[str, list[list[str]]] = OrderedDict()
    for row in data_rows:
        split_value = _cell(row, split_index) or "General"
        grouped_rows.setdefault(split_value, []).append(row)

    used_slugs: dict[str, int] = {}
    documents: list[_RenderedMarkdown] = []
    for split_value, rows_in_group in grouped_rows.items():
        split_slug = slugify(split_value)
        used_slugs[split_slug] = used_slugs.get(split_slug, 0) + 1
        occurrence = used_slugs[split_slug]
        suffix = split_slug if occurrence == 1 else f"{split_slug}--part-{occurrence:02d}"

        rows_payload: list[str] = [f"## {split_value}"]
        for row in rows_in_group:
            rendered_row = _render_row(row=row, headers=headers, skip_indexes={split_index})
            if rendered_row:
                rows_payload.append(rendered_row)
        file_name = f"{source_slug}--{suffix}.md"
        documents.append(
            _RenderedMarkdown(
                file_name=file_name,
                content=_compose_document(title, "\n\n".join(rows_payload)),
            )
        )
    return documents


def _render_fallback_body(headers: list[str] | None, data_rows: list[list[str]]) -> str:
    chunks: list[str] = []
    for row in data_rows:
        rendered = _render_row(row=row, headers=headers, skip_indexes=set())
        if rendered:
            chunks.append(rendered)
    return "\n\n".join(chunks)


def _render_row(row: list[str], headers: list[str] | None, skip_indexes: set[int]) -> str:
    chunks: list[str] = []
    for index, value in enumerate(row):
        if index in skip_indexes or not value:
            continue

        labelled = split_labelled_cell(value)
        if labelled is not None:
            label, body = labelled
            chunks.append(f"### {label}\n\n{body}")
            continue

        header_name = ""
        if headers is not None and index < len(headers):
            header_name = headers[index]
        if header_name:
            chunks.append(f"**{header_name}:** {value}")
        else:
            chunks.append(value)
    return "\n\n".join(chunks)


def _compose_document(title: str, body: str) -> str:
    normalized_title = normalize_cell_text(title) or "Untitled Knowledge Base"
    normalized_body = normalize_cell_text(body)
    if not normalized_body:
        return f"# {normalized_title}\n"
    return f"# {normalized_title}\n\n{normalized_body}\n"


def _build_header_map(header_row: list[str]) -> dict[str, int]:
    header_map: dict[str, int] = {}
    for index, header_value in enumerate(header_row):
        if not header_value:
            continue
        normalized = normalize_header_name(header_value)
        if normalized and normalized not in header_map:
            header_map[normalized] = index
    return header_map


def _resolve_column_index(header_map: dict[str, int], column_name: str) -> int | None:
    return header_map.get(normalize_header_name(column_name))


def _resolve_logical_id(config: ParseConfig, override: FileOverride, source_slug: str) -> str:
    if override.logical_id:
        return override.logical_id
    if source_slug in config.logical_id_overrides:
        return config.logical_id_overrides[source_slug]
    return source_slug


def _resolve_file_override(config: ParseConfig, source_name: str) -> FileOverride:
    direct_match = config.files.get(source_name)
    if direct_match is not None:
        return direct_match

    folded_source_name = source_name.casefold()
    for file_name, override in config.files.items():
        if file_name.casefold() == folded_source_name:
            return override
    return FileOverride()


def _cleanup_previous_outputs(markdown_dir: Path, source_slug: str) -> None:
    exact_file = markdown_dir / f"{source_slug}.md"
    if exact_file.exists():
        exact_file.unlink()
    for existing_file in markdown_dir.glob(f"{source_slug}--*.md"):
        existing_file.unlink()


def _write_manifest(
    manifest_path: Path,
    input_dir: Path,
    output_dir: Path,
    entries: list[ManifestEntry],
    errors: list[FileParseError],
) -> None:
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


def _as_optional_str(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    normalized = normalize_cell_text(str(raw_value))
    return normalized or None


def _as_split_mode(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    normalized = normalize_cell_text(str(raw_value)).casefold()
    if normalized in {"single", "column"}:
        return normalized
    return None


def _as_dict(raw_value: object) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        return raw_value
    return {}


def _cell(row: list[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return row[index]
