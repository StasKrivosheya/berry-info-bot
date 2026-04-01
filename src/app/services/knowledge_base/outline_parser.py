from __future__ import annotations

from dataclasses import dataclass

from app.services.knowledge_base.markdown_render import RenderedMarkdown
from app.services.knowledge_base.normalizer import normalize_cell_text, split_labelled_cell
from app.services.knowledge_base.types import ParseDiagnostic, SourceOverride
from app.services.knowledge_base.xlsx_ingest import (
    PreparedWorkbookSheet,
    SheetRow,
    select_outline_rows,
)

HEADER_CUE_ROW_HEIGHT = 22.0
HEADER_MAX_TEXT_LENGTH = 100
HEADER_MAX_WORDS = 14

BULLET_PREFIXES = (
    "-",
    "*",
    "+",
    "\U0001f539",
    "\u2022",
    "\u2713",
    "\u2714",
    "\u25aa",
    "\u25ab",
    "\u25e6",
    "\u2023",
)

DIAGNOSTIC_AMBIGUOUS_SHORT_ROW = "ambiguous_short_row"
DIAGNOSTIC_INLINE_HEADER_UNSUPPORTED = "inline_header_in_same_cell_unsupported"


@dataclass(frozen=True, slots=True)
class OutlineBlock:
    kind: str
    text: str


@dataclass(frozen=True, slots=True)
class OutlineCandidate:
    row_index: int
    column_index: int
    row_cell_count: int
    text: str
    is_bold: bool
    merged_span: int
    row_height: float | None
    gap_before: int
    gap_after: int


class OutlineParseError(ValueError):
    diagnostics: list[ParseDiagnostic]

    def __init__(self, message: str, diagnostics: list[ParseDiagnostic]) -> None:
        ValueError.__init__(self, message)
        self.diagnostics = diagnostics


def render_outline_sheet(
    *,
    sheet: PreparedWorkbookSheet,
    source_slug: str,
    default_title: str,
    override: SourceOverride,
) -> tuple[str, list[RenderedMarkdown], int, int]:
    selected_rows = select_outline_rows(sheet, override)
    if not selected_rows:
        msg = f"Worksheet '{sheet.sheet_name}' has no non-empty rows after outline filtering."
        raise OutlineParseError(msg, diagnostics=[])

    diagnostics: list[ParseDiagnostic] = []
    blocks: list[OutlineBlock] = []
    document_title = normalize_cell_text(default_title) or "Untitled Knowledge Base"
    has_title = False

    candidates = _build_candidates(selected_rows)
    first_row_index = candidates[0].row_index
    non_empty_cell_count = sum(len(row.cells) for row in selected_rows)
    for candidate in candidates:
        classification, row_diagnostics = _classify_candidate(
            candidate=candidate,
            first_row_index=first_row_index,
            has_title=has_title,
            override=override,
        )
        diagnostics.extend(row_diagnostics)
        if classification is None:
            continue
        if classification.kind == "title" and not has_title:
            document_title = classification.text
            has_title = True
            continue
        blocks.append(classification)

    diagnostics = _dedupe_diagnostics(diagnostics)
    if diagnostics:
        msg = f"Worksheet '{sheet.sheet_name}' has ambiguous outline rows."
        raise OutlineParseError(msg, diagnostics=diagnostics)

    body = "\n\n".join(_render_block(block) for block in blocks if block.text)
    markdown = _compose_document(document_title, body)
    return (
        "outline_sheet",
        [RenderedMarkdown(file_name=f"{source_slug}.md", content=markdown)],
        len(selected_rows),
        non_empty_cell_count,
    )


def _build_candidates(selected_rows: list[SheetRow]) -> list[OutlineCandidate]:
    candidates: list[OutlineCandidate] = []
    for index, row in enumerate(selected_rows):
        previous_row = selected_rows[index - 1] if index > 0 else None
        next_row = selected_rows[index + 1] if index + 1 < len(selected_rows) else None
        gap_before = 1 if previous_row is None else row.row_index - previous_row.row_index
        gap_after = 1 if next_row is None else next_row.row_index - row.row_index
        for cell in sorted(row.cells, key=lambda item: item.column_index):
            candidates.append(
                OutlineCandidate(
                    row_index=row.row_index,
                    column_index=cell.column_index,
                    row_cell_count=len(row.cells),
                    text=cell.text,
                    is_bold=cell.is_bold,
                    merged_span=cell.merged_span,
                    row_height=row.row_height,
                    gap_before=gap_before,
                    gap_after=gap_after,
                )
            )
    return candidates


def _classify_candidate(
    *,
    candidate: OutlineCandidate,
    first_row_index: int,
    has_title: bool,
    override: SourceOverride,
) -> tuple[OutlineBlock | None, list[ParseDiagnostic]]:
    text = candidate.text
    if not text:
        return None, []

    if candidate.row_index in set(override.forced_paragraph_rows):
        return OutlineBlock(kind="paragraph", text=text), []

    force_header = candidate.row_index in set(override.forced_header_rows)
    if force_header:
        kind = (
            "title"
            if candidate.row_index == first_row_index and not has_title
            else "section_header"
        )
        return OutlineBlock(kind=kind, text=text), []

    labelled = split_labelled_cell(text)
    if labelled is not None:
        label, body = labelled
        return OutlineBlock(kind="label_value", text=f"{label}\n\n{body}"), []

    inline_heading = _split_multiline_heading_block(text)
    if inline_heading is not None:
        heading, body = inline_heading
        return OutlineBlock(kind="label_value", text=f"{heading}\n\n{body}"), []

    if _looks_like_ambiguous_inline_heading_block(candidate, text):
        return None, [
            ParseDiagnostic(
                code=DIAGNOSTIC_INLINE_HEADER_UNSUPPORTED,
                message=(
                    "Detected a possible heading on the first line of a multiline cell. "
                    "Exported XLSX does not reliably preserve inline rich-text structure for "
                    "this case, so the sheet must be re-authored or explicitly simplified."
                ),
                row_numbers=(candidate.row_index,),
            )
        ]

    headerish = _is_headerish_text(text)
    strong_header_cue = _has_strong_header_cue(candidate) or _looks_like_display_header(text)
    if candidate.row_index == first_row_index and headerish:
        strong_header_cue = True
    if force_header or (headerish and strong_header_cue):
        kind = (
            "title"
            if candidate.row_index == first_row_index and not has_title
            else "section_header"
        )
        return OutlineBlock(kind=kind, text=text), []

    if candidate.row_cell_count > 1:
        return OutlineBlock(kind="paragraph", text=text), []

    if headerish:
        return None, [
            ParseDiagnostic(
                code=DIAGNOSTIC_AMBIGUOUS_SHORT_ROW,
                message=(
                    "This short standalone row could be either a section header or regular text. "
                    "Add a stronger sheet cue or a parser hint."
                ),
                row_numbers=(candidate.row_index,),
            )
        ]

    if _looks_like_list(text):
        return OutlineBlock(kind="list", text=text), []

    return OutlineBlock(kind="paragraph", text=text), []


def _has_strong_header_cue(candidate: OutlineCandidate) -> bool:
    if candidate.merged_span >= 3:
        return True
    if candidate.is_bold:
        return True
    if candidate.row_height is not None and candidate.row_height >= HEADER_CUE_ROW_HEIGHT:
        return True
    return candidate.gap_before > 1 or candidate.gap_after > 1


def _is_headerish_text(text: str) -> bool:
    normalized = normalize_cell_text(text)
    if not normalized or "\n" in normalized:
        return False
    if _starts_with_bullet(normalized):
        return False
    if normalized.endswith("."):
        return False
    if len(normalized) > HEADER_MAX_TEXT_LENGTH:
        return False
    return len(normalized.split()) <= HEADER_MAX_WORDS


def _split_multiline_heading_block(text: str) -> tuple[str, str] | None:
    lines = [line for line in normalize_cell_text(text).splitlines() if line]
    if len(lines) < 2:
        return None
    first_line = lines[0]
    body = normalize_cell_text("\n".join(lines[1:]))
    if not body:
        return None
    if first_line.endswith(":"):
        return first_line[:-1].strip(), body
    if first_line.endswith("?"):
        return first_line, body
    return None


def _looks_like_ambiguous_inline_heading_block(
    candidate: OutlineCandidate,
    text: str,
) -> bool:
    lines = [line for line in normalize_cell_text(text).splitlines() if line]
    if len(lines) < 2:
        return False
    first_line = lines[0]
    if first_line.endswith(":") or first_line.endswith("?"):
        return False
    if _starts_with_bullet(first_line):
        return False
    if not _is_headerish_text(first_line):
        return False

    if any(_starts_with_bullet(line) for line in lines[1:]):
        return len(first_line.split()) <= 6

    return _has_strong_header_cue(candidate) or _looks_like_display_header(first_line)


def _looks_like_list(text: str) -> bool:
    lines = [line for line in normalize_cell_text(text).splitlines() if line]
    if not lines:
        return False
    return all(_starts_with_bullet(line) for line in lines)


def _starts_with_bullet(value: str) -> bool:
    normalized = value.lstrip()
    return any(normalized.startswith(prefix) for prefix in BULLET_PREFIXES)


def _render_block(block: OutlineBlock) -> str:
    if block.kind == "section_header":
        return f"## {block.text}"
    if block.kind == "label_value":
        label, _, body = block.text.partition("\n\n")
        return f"### {label}\n\n{body}"
    return block.text


def _looks_like_display_header(text: str) -> bool:
    normalized = normalize_cell_text(text)
    letters = [character for character in normalized if character.isalpha()]
    if letters and normalized == normalized.upper():
        return True
    return "«" in normalized and "»" in normalized and len(normalized.split()) <= HEADER_MAX_WORDS


def _dedupe_diagnostics(diagnostics: list[ParseDiagnostic]) -> list[ParseDiagnostic]:
    seen: set[tuple[str, tuple[int, ...], str]] = set()
    unique: list[ParseDiagnostic] = []
    for diagnostic in diagnostics:
        key = (diagnostic.code, diagnostic.row_numbers, diagnostic.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(diagnostic)
    return unique


def _compose_document(title: str, body: str) -> str:
    normalized_title = normalize_cell_text(title) or "Untitled Knowledge Base"
    normalized_body = normalize_cell_text(body)
    if not normalized_body:
        return f"# {normalized_title}\n"
    return f"# {normalized_title}\n\n{normalized_body}\n"
