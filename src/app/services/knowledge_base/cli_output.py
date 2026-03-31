from __future__ import annotations

import json

from app.services.knowledge_base.types_openai import (
    NO_RELEVANT_INFO_FALLBACK,
    SearchResponse,
    SyncReport,
)


def render_sync_report(report: SyncReport) -> str:
    """Render sync report as stable JSON for scripts and future admin flows."""

    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)


def render_smoke_test_output(query: str, response: SearchResponse) -> str:
    """Render smoke-test output deterministically."""

    lines = [
        f"query: {query}",
        (
            "result_count: "
            f"{len(response.results)} "
            f"(threshold={response.used_threshold}, top_score={response.top_score}, "
            f"fallback_triggered={response.fallback_triggered})"
        ),
    ]
    for index, hit in enumerate(response.results, start=1):
        logical_id = hit.attributes.get("logical_id", "")
        category = hit.attributes.get("category", "")
        excerpt = _make_excerpt(hit.text)
        lines.append(f"{index}. score={hit.score:.4f} file={hit.filename} file_id={hit.file_id}")
        lines.append(f"   logical_id={logical_id} category={category}")
        lines.append(f"   excerpt={excerpt}")

    if response.fallback_triggered:
        lines.append(response.fallback_message or NO_RELEVANT_INFO_FALLBACK)
    return "\n".join(lines)


def _make_excerpt(text: str, max_len: int = 220) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 3].rstrip() + "..."
