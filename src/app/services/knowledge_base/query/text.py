# ruff: noqa: RUF001

from __future__ import annotations

import re

from app.services.knowledge_base.normalizer import normalize_cell_text

TOKEN_RE = re.compile(r"[\w']+", flags=re.UNICODE)
STOPWORDS = {
    "а",
    "або",
    "без",
    "бути",
    "в",
    "вас",
    "ви",
    "від",
    "для",
    "до",
    "де",
    "дуже",
    "за",
    "з",
    "й",
    "і",
    "із",
    "його",
    "їх",
    "її",
    "є",
    "як",
    "яка",
    "яке",
    "який",
    "які",
    "коли",
    "мене",
    "мені",
    "ми",
    "може",
    "можете",
    "можна",
    "на",
    "над",
    "не",
    "ні",
    "ну",
    "о",
    "під",
    "по",
    "про",
    "та",
    "те",
    "ти",
    "то",
    "у",
    "це",
    "цей",
    "ця",
    "що",
    "щось",
}


def normalize_query_text(query: str) -> str:
    return normalize_cell_text(query).casefold()


def tokenize_text(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for raw_token in TOKEN_RE.findall(normalize_query_text(text)):
        normalized = raw_token.strip("'_")
        if len(normalized) <= 1:
            continue
        if normalized in STOPWORDS:
            continue
        tokens.append(_token_key(normalized))
    return tuple(tokens)


def token_overlap_score(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    if not left or not right:
        return 0
    return len(set(left) & set(right))


def strip_leading_markers(text: str) -> str:
    value = text.strip()
    while value and not (value[0].isalnum() or value[0] in {'"', "«", "("}):
        value = value[1:].lstrip()
    return normalize_cell_text(value)


def shorten_text(text: str, *, limit: int = 120) -> str:
    normalized = normalize_cell_text(text)
    if len(normalized) <= limit:
        return normalized
    truncated = normalized[: limit - 1].rstrip()
    return truncated + "..."


def _token_key(token: str) -> str:
    return token[:6] if len(token) > 6 else token
