from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from app.services.knowledge_base.normalizer import (
    normalize_cell_text,
    normalize_header_name,
    slugify,
    split_labelled_cell,
)
from app.services.knowledge_base.types import FileOverride


@dataclass(slots=True)
class RenderedMarkdown:
    file_name: str
    content: str


def render_documents(
    *,
    rows: list[list[str]],
    source_slug: str,
    title: str,
    override: FileOverride,
) -> tuple[str, list[RenderedMarkdown]]:
    """Render markdown documents using deterministic mode dispatch."""

    header_map = _build_header_map(rows[0])
    mode_resolvers = (
        _qa_mode_render,
        _section_mode_render,
        _column_split_mode_render,
    )
    for resolver in mode_resolvers:
        resolved = resolver(
            rows=rows,
            source_slug=source_slug,
            title=title,
            override=override,
            header_map=header_map,
        )
        if resolved is not None:
            return resolved

    return _fallback_mode_render(rows=rows, source_slug=source_slug, title=title)


def infer_fallback_headers(rows: list[list[str]]) -> tuple[list[str] | None, list[list[str]]]:
    """Infer header presence for ambiguous fallback parsing."""

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


def _qa_mode_render(
    *,
    rows: list[list[str]],
    source_slug: str,
    title: str,
    override: FileOverride,
    header_map: dict[str, int],
) -> tuple[str, list[RenderedMarkdown]] | None:
    qa_mode = _resolve_qa_mode(override, header_map)
    if qa_mode is None:
        return None

    body = _render_qa_body(
        headers=rows[0],
        data_rows=rows[1:],
        question_index=qa_mode["question_index"],
        answer_index=qa_mode["answer_index"],
        section_index=qa_mode.get("section_index"),
    )
    docs = [
        RenderedMarkdown(
            file_name=f"{source_slug}.md",
            content=_compose_document(title, body),
        )
    ]
    return "qa", docs


def _section_mode_render(
    *,
    rows: list[list[str]],
    source_slug: str,
    title: str,
    override: FileOverride,
    header_map: dict[str, int],
) -> tuple[str, list[RenderedMarkdown]] | None:
    section_mode = _resolve_section_mode(override, header_map)
    if section_mode is None:
        return None

    body = _render_section_body(
        headers=rows[0],
        data_rows=rows[1:],
        section_index=section_mode["section_index"],
    )
    docs = [
        RenderedMarkdown(
            file_name=f"{source_slug}.md",
            content=_compose_document(title, body),
        )
    ]
    return "section", docs


def _column_split_mode_render(
    *,
    rows: list[list[str]],
    source_slug: str,
    title: str,
    override: FileOverride,
    header_map: dict[str, int],
) -> tuple[str, list[RenderedMarkdown]] | None:
    split_mode = _resolve_split_mode(override, header_map)
    if split_mode is None:
        return None

    docs = _render_split_documents(
        source_slug=source_slug,
        title=title,
        headers=rows[0],
        data_rows=rows[1:],
        split_index=split_mode["split_index"],
    )
    return "column_split", docs


def _fallback_mode_render(
    *,
    rows: list[list[str]],
    source_slug: str,
    title: str,
) -> tuple[str, list[RenderedMarkdown]]:
    inferred_headers, data_rows = infer_fallback_headers(rows)
    body = _render_fallback_body(headers=inferred_headers, data_rows=data_rows)
    docs = [
        RenderedMarkdown(
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
    split_mode = (override.split_mode or "single").casefold()
    if split_mode != "column" or not override.split_column_name:
        return None

    split_index = _resolve_column_index(header_map, override.split_column_name)
    if split_index is None:
        return None
    return {"split_index": split_index}


def _render_qa_body(
    *,
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
    *,
    source_slug: str,
    title: str,
    headers: list[str],
    data_rows: list[list[str]],
    split_index: int,
) -> list[RenderedMarkdown]:
    grouped_rows: OrderedDict[str, list[list[str]]] = OrderedDict()
    for row in data_rows:
        split_value = _cell(row, split_index) or "General"
        grouped_rows.setdefault(split_value, []).append(row)

    used_slugs: dict[str, int] = {}
    documents: list[RenderedMarkdown] = []
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
            RenderedMarkdown(
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


def _cell(row: list[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return row[index]

