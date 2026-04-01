from __future__ import annotations

import hashlib
import re
import unicodedata

INLINE_WHITESPACE_RE = re.compile(r"[ \t]+")
ASCII_SLUG_RE = re.compile(r"[^a-z0-9]+")
UNICODE_SLUG_RE = re.compile(r"[^\w]+", flags=re.UNICODE)
MULTI_DASH_RE = re.compile(r"-{2,}")
LABELLED_CELL_RE = re.compile(r"^\s*([^:\n]{1,80}):\s*(.+?)\s*$", flags=re.DOTALL)
CYRILLIC_SLUG_MAP = {
    "\u0430": "a",
    "\u0431": "b",
    "\u0432": "v",
    "\u0433": "h",
    "\u0491": "g",
    "\u0434": "d",
    "\u0435": "e",
    "\u0454": "ie",
    "\u0436": "zh",
    "\u0437": "z",
    "\u0438": "y",
    "\u0456": "i",
    "\u0457": "i",
    "\u0439": "i",
    "\u043a": "k",
    "\u043b": "l",
    "\u043c": "m",
    "\u043d": "n",
    "\u043e": "o",
    "\u043f": "p",
    "\u0440": "r",
    "\u0441": "s",
    "\u0442": "t",
    "\u0443": "u",
    "\u0444": "f",
    "\u0445": "kh",
    "\u0446": "ts",
    "\u0447": "ch",
    "\u0448": "sh",
    "\u0449": "shch",
    "\u044c": "",
    "\u044e": "iu",
    "\u044f": "ia",
    "\u0451": "io",
    "\u044d": "e",
    "\u044b": "y",
    "\u044a": "",
}


def normalize_cell_text(value: str) -> str:
    """Normalize whitespace while preserving paragraph boundaries."""

    text = value.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ").strip()
    if not text:
        return ""

    normalized_lines: list[str] = []
    previous_blank = False
    for raw_line in text.split("\n"):
        line = INLINE_WHITESPACE_RE.sub(" ", raw_line.strip())
        if not line:
            if normalized_lines and not previous_blank:
                normalized_lines.append("")
            previous_blank = True
            continue
        normalized_lines.append(line)
        previous_blank = False

    while normalized_lines and normalized_lines[-1] == "":
        normalized_lines.pop()
    return "\n".join(normalized_lines)


def normalize_header_name(value: str) -> str:
    return normalize_cell_text(value).casefold()


def is_non_empty_text(value: str) -> bool:
    return bool(normalize_cell_text(value))


def slugify(value: str) -> str:
    """Generate deterministic slug values for file names and logical ids."""

    normalized = normalize_cell_text(value).casefold()
    if not normalized:
        return "item"

    transliterated = "".join(
        CYRILLIC_SLUG_MAP.get(character, character) for character in normalized
    )
    ascii_text = unicodedata.normalize("NFKD", transliterated).encode("ascii", "ignore").decode(
        "ascii"
    )
    ascii_slug = ASCII_SLUG_RE.sub("-", ascii_text).strip("-")
    ascii_slug = MULTI_DASH_RE.sub("-", ascii_slug)
    if ascii_slug:
        return ascii_slug

    unicode_slug = UNICODE_SLUG_RE.sub("-", normalized).strip("-").replace("_", "-")
    unicode_slug = MULTI_DASH_RE.sub("-", unicode_slug)
    return unicode_slug or "item"


def legacy_ascii_slugify(value: str) -> str:
    """Reproduce the earlier ASCII-stripping slug behavior for cleanup compatibility."""

    normalized = normalize_cell_text(value).casefold()
    if not normalized:
        return "item"

    ascii_text = unicodedata.normalize("NFKD", normalized).encode("ascii", "ignore").decode("ascii")
    ascii_slug = ASCII_SLUG_RE.sub("-", ascii_text).strip("-")
    ascii_slug = MULTI_DASH_RE.sub("-", ascii_slug)
    if ascii_slug:
        return ascii_slug

    unicode_slug = UNICODE_SLUG_RE.sub("-", normalized).strip("-").replace("_", "-")
    unicode_slug = MULTI_DASH_RE.sub("-", unicode_slug)
    return unicode_slug or "item"


def prettify_title(value: str) -> str:
    cleaned = re.sub(r"[-_]+", " ", value).strip()
    if not cleaned:
        return "Untitled Knowledge Base"
    return INLINE_WHITESPACE_RE.sub(" ", cleaned).title()


def compute_content_hash(chunks: list[str]) -> str:
    hasher = hashlib.sha256()
    for chunk in chunks:
        hasher.update(chunk.encode("utf-8"))
    return hasher.hexdigest()


def split_labelled_cell(value: str) -> tuple[str, str] | None:
    """Return (label, body) when a cell looks like 'Label: content'."""

    match = LABELLED_CELL_RE.match(value)
    if not match:
        return None
    if "://" in value:
        return None

    label = normalize_cell_text(match.group(1))
    body = normalize_cell_text(match.group(2))
    if label.casefold() in {"http", "https"}:
        return None
    if not label or not body:
        return None
    return label, body
