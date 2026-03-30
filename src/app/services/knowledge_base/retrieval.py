from __future__ import annotations

import json
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any

from app.services.knowledge_base.kb_openai_config import (
    MAX_SCORE_THRESHOLD,
    MAX_SEARCH_RESULTS,
    MIN_SCORE_THRESHOLD,
    MIN_SEARCH_RESULTS,
    KnowledgeBaseOpenAISettings,
    get_kb_openai_settings,
)
from app.services.knowledge_base.types_openai import (
    NO_RELEVANT_INFO_FALLBACK,
    Attributes,
    ManifestSyncItem,
    SearchHit,
    SearchResponse,
    SyncFailure,
    SyncReport,
    VectorStoreFileRecord,
)
from app.services.knowledge_base.vector_store import KnowledgeBaseVectorStoreClient

logger = logging.getLogger(__name__)

LOG_EVENT_MANIFEST_LOADED = "kb_manifest_loaded"
LOG_EVENT_SYNC_STARTED = "kb_vector_sync_started"
LOG_EVENT_SYNC_COMPLETED = "kb_vector_sync_completed"
LOG_EVENT_SYNC_SKIPPED_BY_FILTER = "kb_vector_sync_filtered"
LOG_EVENT_SEARCH_COMPLETED = "kb_vector_search_completed"


class KnowledgeBaseRetrievalService:
    """High-level knowledge-base service for vector sync and retrieval."""

    def __init__(
        self,
        vector_store_client: KnowledgeBaseVectorStoreClient | None = None,
        settings: KnowledgeBaseOpenAISettings | None = None,
    ) -> None:
        self._settings = settings or get_kb_openai_settings()
        self._vector_store_client = vector_store_client or KnowledgeBaseVectorStoreClient(
            settings=self._settings
        )

    def ensure_vector_store(self) -> Any:
        return self._vector_store_client.ensure_vector_store()

    def list_vector_store_files(self) -> list[VectorStoreFileRecord]:
        return self._vector_store_client.list_vector_store_files()

    def delete_files_by_logical_id(
        self,
        logical_id: str,
        *,
        existing_files: list[VectorStoreFileRecord] | None = None,
        delete_underlying: bool = True,
        dry_run: bool = False,
    ) -> Any:
        return self._vector_store_client.delete_files_by_logical_id(
            logical_id,
            existing_files=existing_files,
            delete_underlying=delete_underlying,
            dry_run=dry_run,
        )

    def upload_markdown_file(
        self,
        markdown_path: Path,
        *,
        attributes: Attributes,
        dry_run: bool = False,
    ) -> Any:
        return self._vector_store_client.upload_markdown_file(
            markdown_path=markdown_path,
            attributes=attributes,
            dry_run=dry_run,
        )

    def sync_from_manifest(
        self,
        manifest_path: Path,
        *,
        replace: bool = True,
        dry_run: bool = False,
        only_logical_id: str | None = None,
        only_category: str | None = None,
    ) -> SyncReport:
        """Sync manifest-derived markdown files into vector store with replace-by-logical_id.

        This method is intentionally framework-agnostic so future admin commands (for example,
        `/kb_refresh`) can trigger the same deterministic sync flow without duplicating logic.
        """

        manifest_path = manifest_path.resolve()
        self.ensure_vector_store()
        items = _load_manifest_sync_items(manifest_path)

        report = SyncReport(
            manifest_path=manifest_path,
            dry_run=dry_run,
            replace=replace,
            scanned_count=len(items),
        )

        selected_items = [
            item
            for item in items
            if (only_logical_id is None or item.logical_id == only_logical_id)
            and (only_category is None or item.category == only_category)
        ]
        report.selected_count = len(selected_items)
        report.skipped_count = report.scanned_count - report.selected_count
        logger.info(
            "%s manifest=%s scanned=%s selected=%s skipped=%s only_logical_id=%s only_category=%s",
            LOG_EVENT_SYNC_STARTED,
            manifest_path.as_posix(),
            report.scanned_count,
            report.selected_count,
            report.skipped_count,
            only_logical_id,
            only_category,
        )
        if report.skipped_count > 0:
            logger.info(
                "%s skipped_count=%s",
                LOG_EVENT_SYNC_SKIPPED_BY_FILTER,
                report.skipped_count,
            )

        grouped_items: OrderedDict[str, list[ManifestSyncItem]] = OrderedDict()
        for item in sorted(
            selected_items,
            key=lambda value: (value.logical_id, value.markdown_relative_path.casefold()),
        ):
            grouped_items.setdefault(item.logical_id, []).append(item)

        existing_files = self.list_vector_store_files() if replace else []
        for logical_id, group in grouped_items.items():
            if replace:
                try:
                    delete_report = self.delete_files_by_logical_id(
                        logical_id,
                        existing_files=existing_files,
                        delete_underlying=True,
                        dry_run=dry_run,
                    )
                    report.deleted_count += delete_report.deleted_count
                    report.deleted_underlying_count += delete_report.deleted_underlying_count
                    existing_files = [
                        record
                        for record in existing_files
                        if record.attributes.get("logical_id") != logical_id
                    ]
                except Exception as exc:
                    report.failures.append(
                        SyncFailure(
                            operation="delete",
                            logical_id=logical_id,
                            markdown_path=None,
                            error_type=type(exc).__name__,
                            message=str(exc),
                        )
                    )
                    report.skipped_count += len(group)
                    continue

            for item in group:
                try:
                    self.upload_markdown_file(
                        item.markdown_absolute_path,
                        attributes=item.upload_attributes,
                        dry_run=dry_run,
                    )
                    report.uploaded_count += 1
                except Exception as exc:
                    report.failures.append(
                        SyncFailure(
                            operation="upload",
                            logical_id=item.logical_id,
                            markdown_path=item.markdown_absolute_path.as_posix(),
                            error_type=type(exc).__name__,
                            message=str(exc),
                        )
                    )

        logger.info(
            "%s scanned=%s selected=%s deleted=%s deleted_underlying=%s uploaded=%s failed=%s",
            LOG_EVENT_SYNC_COMPLETED,
            report.scanned_count,
            report.selected_count,
            report.deleted_count,
            report.deleted_underlying_count,
            report.uploaded_count,
            report.failed_count,
        )
        return report

    def search(
        self,
        query: str,
        *,
        max_num_results: int | None = None,
        rewrite_query: bool = False,
        score_threshold: float | None = None,
        category: str | None = None,
        logical_id: str | None = None,
        attribute_filters: Attributes | None = None,
    ) -> SearchResponse:
        resolved_max_results = _clamp_max_results(
            max_num_results
            if max_num_results is not None
            else self._settings.openai_kb_search_max_results
        )
        resolved_score_threshold = _clamp_score_threshold(
            score_threshold
            if score_threshold is not None
            else self._settings.openai_kb_score_threshold
        )

        merged_filters: Attributes = {"language": "uk"}
        if attribute_filters:
            merged_filters.update(attribute_filters)
        if category is not None:
            merged_filters["category"] = category
        if logical_id is not None:
            merged_filters["logical_id"] = logical_id
        filters_payload = _build_filters_payload(merged_filters)

        response = self._vector_store_client.search(
            query=query,
            max_num_results=resolved_max_results,
            rewrite_query=rewrite_query,
            score_threshold=resolved_score_threshold,
            filters=filters_payload,
        )

        hits = [
            SearchHit(
                file_id=str(item.file_id),
                filename=str(item.filename),
                score=float(item.score),
                attributes=_normalize_attributes(getattr(item, "attributes", None)),
                text=_extract_text(getattr(item, "content", [])),
            )
            for item in response.data
        ]
        hits.sort(key=lambda hit: (-hit.score, hit.file_id, hit.filename))
        top_score = hits[0].score if hits else None

        fallback_triggered = top_score is None or top_score < resolved_score_threshold
        if fallback_triggered:
            filtered_results: list[SearchHit] = []
            fallback_message = NO_RELEVANT_INFO_FALLBACK
        else:
            filtered_results = [
                hit for hit in hits if hit.score >= resolved_score_threshold
            ][:resolved_max_results]
            fallback_message = None

        logger.info(
            "%s query=%s result_count=%s top_score=%s threshold=%s",
            LOG_EVENT_SEARCH_COMPLETED,
            query,
            len(filtered_results),
            top_score,
            resolved_score_threshold,
        )
        return SearchResponse(
            results=filtered_results,
            top_score=top_score,
            used_threshold=resolved_score_threshold,
            fallback_triggered=fallback_triggered,
            fallback_message=fallback_message,
        )


def _load_manifest_sync_items(manifest_path: Path) -> list[ManifestSyncItem]:
    if not manifest_path.exists():
        msg = f"Manifest file does not exist: {manifest_path.as_posix()}"
        raise FileNotFoundError(msg)

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        msg = "Manifest payload must include 'entries' list."
        raise ValueError(msg)

    output_dir = _resolve_output_dir(
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


def _resolve_output_dir(manifest_path: Path, raw_output_dir: object) -> Path:
    if isinstance(raw_output_dir, str) and raw_output_dir.strip():
        output_dir = Path(raw_output_dir.strip())
        if output_dir.is_absolute():
            return output_dir

        cwd_candidate = (Path.cwd() / output_dir).resolve()
        if cwd_candidate.exists():
            return cwd_candidate

        return (manifest_path.parent / output_dir).resolve()

    return manifest_path.parent.resolve()


def _build_filters_payload(filters: Attributes) -> dict[str, Any] | None:
    if not filters:
        return None

    filter_items = [
        {
            "type": "eq",
            "key": key,
            "value": value,
        }
        for key, value in sorted(filters.items(), key=lambda item: item[0])
    ]
    if len(filter_items) == 1:
        return filter_items[0]
    return {
        "type": "and",
        "filters": filter_items,
    }


def _extract_text(content_items: object) -> str:
    if not isinstance(content_items, list):
        return ""

    chunks: list[str] = []
    for item in content_items:
        item_type = getattr(item, "type", None)
        item_text = getattr(item, "text", None)
        if item_type == "text" and isinstance(item_text, str) and item_text.strip():
            chunks.append(item_text.strip())
    return "\n\n".join(chunks)


def _normalize_attributes(raw_attributes: object) -> Attributes:
    if not isinstance(raw_attributes, dict):
        return {}

    normalized: Attributes = {}
    for key, value in raw_attributes.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, (str, float, bool)):
            normalized[key] = value
            continue
        if isinstance(value, int):
            normalized[key] = float(value)
    return normalized


def _clamp_max_results(value: int) -> int:
    return max(MIN_SEARCH_RESULTS, min(MAX_SEARCH_RESULTS, value))


def _clamp_score_threshold(value: float) -> float:
    return max(MIN_SCORE_THRESHOLD, min(MAX_SCORE_THRESHOLD, value))
