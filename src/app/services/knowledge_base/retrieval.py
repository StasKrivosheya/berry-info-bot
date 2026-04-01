from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.services.knowledge_base.attribute_utils import (
    build_filters_payload,
    build_search_attributes,
)
from app.services.knowledge_base.kb_openai_config import (
    KnowledgeBaseOpenAISettings,
    clamp_score_threshold,
    clamp_search_max_results,
    get_kb_openai_settings,
)
from app.services.knowledge_base.manifest_reader import (
    load_manifest_error_workbooks,
    load_manifest_sync_items,
)
from app.services.knowledge_base.search_policy import apply_relevance_policy, normalize_search_hits
from app.services.knowledge_base.sync_planner import build_sync_plan
from app.services.knowledge_base.types_openai import (
    Attributes,
    SearchResponse,
    SyncFailure,
    SyncReport,
    VectorStoreFileRecord,
)
from app.services.knowledge_base.vector_store import KnowledgeBaseVectorStoreClient

logger = logging.getLogger(__name__)

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
        items = load_manifest_sync_items(manifest_path)
        manifest_error_workbooks = load_manifest_error_workbooks(manifest_path)
        plan = build_sync_plan(
            items=items,
            only_logical_id=only_logical_id,
            only_category=only_category,
        )

        report = SyncReport(
            manifest_path=manifest_path,
            dry_run=dry_run,
            replace=replace,
            scanned_count=plan.scanned_count,
            selected_count=plan.selected_count,
            skipped_count=plan.skipped_count,
        )
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

        existing_files = self.list_vector_store_files() if replace else []
        if replace and existing_files:
            stale_records = _collect_stale_workbook_records(
                existing_files=existing_files,
                items=plan.selected_items,
                blocked_workbooks=manifest_error_workbooks,
            )
            if stale_records:
                delete_report = self._vector_store_client.delete_file_records(
                    stale_records,
                    delete_underlying=True,
                    dry_run=dry_run,
                )
                report.deleted_count += delete_report.deleted_count
                report.deleted_underlying_count += delete_report.deleted_underlying_count
                stale_file_ids = {record.file_id for record in stale_records}
                existing_files = [
                    record for record in existing_files if record.file_id not in stale_file_ids
                ]

        for logical_id, grouped_items in plan.grouped_items.items():
            if replace:
                try:
                    delete_report = self.delete_files_by_logical_id(
                        logical_id,
                        existing_files=existing_files,
                        delete_underlying=True,
                        dry_run=dry_run,
                    )
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
                    report.skipped_count += len(grouped_items)
                    continue

                report.deleted_count += delete_report.deleted_count
                report.deleted_underlying_count += delete_report.deleted_underlying_count
                existing_files = [
                    record
                    for record in existing_files
                    if record.attributes.get("logical_id") != logical_id
                ]

            for item in grouped_items:
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
        resolved_threshold = _clamp_score_threshold(
            score_threshold
            if score_threshold is not None
            else self._settings.openai_kb_score_threshold
        )

        merged_filters = build_search_attributes(
            attribute_filters=attribute_filters,
            category=category,
            logical_id=logical_id,
            language="uk",
        )
        response = self._vector_store_client.search(
            query=query,
            max_num_results=resolved_max_results,
            rewrite_query=rewrite_query,
            score_threshold=resolved_threshold,
            filters=build_filters_payload(merged_filters),
        )
        normalized_hits = normalize_search_hits(response.data)
        result = apply_relevance_policy(
            hits=normalized_hits,
            threshold=resolved_threshold,
            max_results=resolved_max_results,
        )
        logger.info(
            "%s query=%s result_count=%s top_score=%s threshold=%s",
            LOG_EVENT_SEARCH_COMPLETED,
            query,
            len(result.results),
            result.top_score,
            result.used_threshold,
        )
        return result


def _clamp_max_results(value: int) -> int:
    return clamp_search_max_results(value)


def _clamp_score_threshold(value: float) -> float:
    return clamp_score_threshold(value)


def _collect_stale_workbook_records(
    *,
    existing_files: list[VectorStoreFileRecord],
    items,
    blocked_workbooks: set[str],
) -> list[VectorStoreFileRecord]:
    workbook_state = _build_workbook_state(items)
    stale_records: list[VectorStoreFileRecord] = []
    seen_file_ids: set[str] = set()

    for record in existing_files:
        workbook_file = _attribute_as_str(record.attributes.get("workbook_file"))
        if not workbook_file or workbook_file in blocked_workbooks:
            continue

        state = workbook_state.get(workbook_file)
        if state is None:
            continue

        if _is_stale_workbook_record(record, state):
            if record.file_id in seen_file_ids:
                continue
            seen_file_ids.add(record.file_id)
            stale_records.append(record)

    return stale_records


def _build_workbook_state(items) -> dict[str, dict[str, object]]:
    workbook_state: dict[str, dict[str, object]] = {}
    for item in items:
        if item.source_format != "xlsx" or not item.workbook_file:
            continue

        state = workbook_state.setdefault(
            item.workbook_file,
            {
                "logical_ids": set(),
                "sheet_names": {},
                "sheet_indexes": {},
            },
        )
        logical_ids = state["logical_ids"]
        if isinstance(logical_ids, set):
            logical_ids.add(item.logical_id)

        if item.sheet_name:
            sheet_names = state["sheet_names"]
            if isinstance(sheet_names, dict):
                allowed_ids = sheet_names.setdefault(item.sheet_name, set())
                if isinstance(allowed_ids, set):
                    allowed_ids.add(item.logical_id)

        if item.sheet_index is not None:
            sheet_indexes = state["sheet_indexes"]
            if isinstance(sheet_indexes, dict):
                allowed_ids = sheet_indexes.setdefault(str(item.sheet_index), set())
                if isinstance(allowed_ids, set):
                    allowed_ids.add(item.logical_id)

    return workbook_state


def _is_stale_workbook_record(
    record: VectorStoreFileRecord,
    state: dict[str, object],
) -> bool:
    record_logical_id = _attribute_as_str(record.attributes.get("logical_id"))
    record_sheet_index = _attribute_as_str(record.attributes.get("sheet_index"))
    record_sheet_name = _attribute_as_str(record.attributes.get("sheet_name"))

    sheet_indexes = state.get("sheet_indexes", {})
    if isinstance(sheet_indexes, dict) and record_sheet_index:
        allowed_ids = sheet_indexes.get(record_sheet_index)
        if isinstance(allowed_ids, set):
            return record_logical_id not in allowed_ids
        return True

    sheet_names = state.get("sheet_names", {})
    if isinstance(sheet_names, dict) and record_sheet_name:
        allowed_ids = sheet_names.get(record_sheet_name)
        if isinstance(allowed_ids, set):
            return record_logical_id not in allowed_ids
        return True

    logical_ids = state.get("logical_ids", set())
    if isinstance(logical_ids, set) and record_logical_id:
        return record_logical_id not in logical_ids
    return False


def _attribute_as_str(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
