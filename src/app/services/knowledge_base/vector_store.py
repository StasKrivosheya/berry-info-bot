from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.services.knowledge_base.attribute_utils import normalize_attributes
from app.services.knowledge_base.kb_openai_config import (
    KnowledgeBaseOpenAISettings,
    get_kb_openai_settings,
)
from app.services.knowledge_base.types_openai import (
    Attributes,
    DeleteRecordsReport,
    DeleteReport,
    UploadResult,
    VectorStoreFileRecord,
)

logger = logging.getLogger(__name__)

LOG_EVENT_VECTOR_STORE_VALIDATED = "kb_vector_store_validated"
LOG_EVENT_VECTOR_STORE_LISTED = "kb_vector_store_files_listed"
LOG_EVENT_VECTOR_STORE_DELETE = "kb_vector_store_files_deleted"
LOG_EVENT_VECTOR_STORE_UPLOAD = "kb_vector_store_file_uploaded"
LOG_EVENT_VECTOR_STORE_SEARCH = "kb_vector_store_search"


def filter_files_by_logical_id(
    files: list[VectorStoreFileRecord],
    logical_id: str,
) -> list[VectorStoreFileRecord]:
    """Return files that match a logical_id exactly (no fuzzy/sub-string match)."""

    return [record for record in files if record.attributes.get("logical_id") == logical_id]


class KnowledgeBaseVectorStoreClient:
    """Low-level OpenAI vector store adapter used by sync and retrieval services."""

    def __init__(
        self,
        settings: KnowledgeBaseOpenAISettings | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self._settings = settings or get_kb_openai_settings()
        self._client = client or OpenAI(api_key=self._settings.openai_api_key.get_secret_value())
        self._vector_store_id = self._settings.openai_vector_store_id
        self._filename_cache: dict[str, str] = {}

    @property
    def vector_store_id(self) -> str:
        return self._vector_store_id

    def ensure_vector_store(self) -> Any:
        """Validate that target vector store exists and is accessible."""

        try:
            vector_store = self._client.vector_stores.retrieve(
                vector_store_id=self._vector_store_id
            )
        except Exception as exc:
            msg = (
                "Unable to access vector store. "
                "Check OPENAI_API_KEY and OPENAI_VECTOR_STORE_ID values."
            )
            raise RuntimeError(msg) from exc

        logger.info(
            "%s vector_store_id=%s",
            LOG_EVENT_VECTOR_STORE_VALIDATED,
            self._vector_store_id,
        )
        return vector_store

    def list_vector_store_files(self) -> list[VectorStoreFileRecord]:
        """List and normalize files currently attached to the vector store."""

        files: list[VectorStoreFileRecord] = []
        page = self._client.vector_stores.files.list(
            vector_store_id=self._vector_store_id,
            limit=100,
            order="asc",
        )
        while True:
            for item in page.data:
                file_id = str(item.id)
                files.append(
                    VectorStoreFileRecord(
                        file_id=file_id,
                        filename=self._resolve_filename(file_id),
                        attributes=normalize_attributes(getattr(item, "attributes", None)),
                    )
                )
            if not page.has_next_page():
                break
            page = page.get_next_page()

        files.sort(
            key=lambda record: (
                str(record.attributes.get("logical_id", "")),
                record.file_id,
            )
        )
        logger.info(
            "%s vector_store_id=%s file_count=%s",
            LOG_EVENT_VECTOR_STORE_LISTED,
            self._vector_store_id,
            len(files),
        )
        return files

    def delete_files_by_logical_id(
        self,
        logical_id: str,
        *,
        existing_files: list[VectorStoreFileRecord] | None = None,
        delete_underlying: bool = True,
        dry_run: bool = False,
    ) -> DeleteReport:
        """Delete files by logical_id from vector store and optionally global files storage."""

        files = existing_files if existing_files is not None else self.list_vector_store_files()
        matching_files = filter_files_by_logical_id(files, logical_id)
        deleted_count = 0
        deleted_underlying_count = 0
        deleted_ids: list[str] = []

        if dry_run:
            deleted_count = len(matching_files)
            deleted_underlying_count = len(matching_files) if delete_underlying else 0
            deleted_ids = [record.file_id for record in matching_files]
        else:
            for record in matching_files:
                self._client.vector_stores.files.delete(
                    file_id=record.file_id,
                    vector_store_id=self._vector_store_id,
                )
                deleted_count += 1
                deleted_ids.append(record.file_id)

                if delete_underlying:
                    self._client.files.delete(record.file_id)
                    deleted_underlying_count += 1

        logger.info(
            (
                "%s vector_store_id=%s logical_id=%s matched=%s deleted=%s "
                "deleted_underlying=%s dry_run=%s"
            ),
            LOG_EVENT_VECTOR_STORE_DELETE,
            self._vector_store_id,
            logical_id,
            len(matching_files),
            deleted_count,
            deleted_underlying_count,
            dry_run,
        )
        return DeleteReport(
            logical_id=logical_id,
            matched_count=len(matching_files),
            deleted_count=deleted_count,
            deleted_underlying_count=deleted_underlying_count,
            deleted_file_ids=deleted_ids,
        )

    def delete_file_records(
        self,
        records: list[VectorStoreFileRecord],
        *,
        delete_underlying: bool = True,
        dry_run: bool = False,
    ) -> DeleteRecordsReport:
        """Delete explicit vector-store file records."""

        unique_records: list[VectorStoreFileRecord] = []
        seen_file_ids: set[str] = set()
        for record in records:
            if record.file_id in seen_file_ids:
                continue
            seen_file_ids.add(record.file_id)
            unique_records.append(record)

        deleted_count = 0
        deleted_underlying_count = 0
        deleted_ids: list[str] = []

        if dry_run:
            deleted_count = len(unique_records)
            deleted_underlying_count = len(unique_records) if delete_underlying else 0
            deleted_ids = [record.file_id for record in unique_records]
        else:
            for record in unique_records:
                self._client.vector_stores.files.delete(
                    file_id=record.file_id,
                    vector_store_id=self._vector_store_id,
                )
                deleted_count += 1
                deleted_ids.append(record.file_id)

                if delete_underlying:
                    self._client.files.delete(record.file_id)
                    deleted_underlying_count += 1

        logger.info(
            (
                "%s vector_store_id=%s scope=explicit_records matched=%s deleted=%s "
                "deleted_underlying=%s dry_run=%s"
            ),
            LOG_EVENT_VECTOR_STORE_DELETE,
            self._vector_store_id,
            len(unique_records),
            deleted_count,
            deleted_underlying_count,
            dry_run,
        )
        return DeleteRecordsReport(
            matched_count=len(unique_records),
            deleted_count=deleted_count,
            deleted_underlying_count=deleted_underlying_count,
            deleted_file_ids=deleted_ids,
        )

    def upload_markdown_file(
        self,
        markdown_path: Path,
        *,
        attributes: Attributes,
        dry_run: bool = False,
    ) -> UploadResult:
        """Upload one markdown file and attach attributes."""

        if not markdown_path.exists():
            msg = f"Markdown file does not exist: {markdown_path.as_posix()}"
            raise FileNotFoundError(msg)
        if not markdown_path.is_file():
            msg = f"Markdown path is not a file: {markdown_path.as_posix()}"
            raise ValueError(msg)

        # Keep ingestion metadata strict and deterministic for retrieval filters.
        upload_attributes = dict(attributes)
        upload_attributes["language"] = "uk"
        logical_id = str(upload_attributes.get("logical_id", ""))
        if dry_run:
            return UploadResult(
                file_id=f"dry-run:{markdown_path.name}",
                filename=markdown_path.name,
                logical_id=logical_id,
                dry_run=True,
            )

        with markdown_path.open("rb") as markdown_file:
            vector_file = self._client.vector_stores.files.upload_and_poll(
                vector_store_id=self._vector_store_id,
                file=markdown_file,
                attributes=upload_attributes,
            )

        status = str(getattr(vector_file, "status", "unknown"))
        if status != "completed":
            last_error = getattr(vector_file, "last_error", None)
            msg = f"Upload did not complete. status={status}, last_error={last_error}"
            raise RuntimeError(msg)

        logger.info(
            "%s vector_store_id=%s file_id=%s logical_id=%s filename=%s",
            LOG_EVENT_VECTOR_STORE_UPLOAD,
            self._vector_store_id,
            vector_file.id,
            logical_id,
            markdown_path.name,
        )
        return UploadResult(
            file_id=str(vector_file.id),
            filename=markdown_path.name,
            logical_id=logical_id,
            dry_run=False,
        )

    def search(
        self,
        *,
        query: str,
        max_num_results: int,
        rewrite_query: bool,
        score_threshold: float,
        filters: dict[str, Any] | None = None,
    ) -> Any:
        """Execute vector-store search and return raw SDK response page."""

        payload: dict[str, Any] = {
            "vector_store_id": self._vector_store_id,
            "query": query,
            "max_num_results": max_num_results,
            "rewrite_query": rewrite_query,
            "ranking_options": {
                "ranker": "auto",
                "score_threshold": score_threshold,
            },
        }
        if filters:
            payload["filters"] = filters

        logger.info(
            (
                "%s vector_store_id=%s query_len=%s max_num_results=%s "
                "score_threshold=%s rewrite_query=%s has_filters=%s"
            ),
            LOG_EVENT_VECTOR_STORE_SEARCH,
            self._vector_store_id,
            len(query),
            max_num_results,
            score_threshold,
            rewrite_query,
            bool(filters),
        )
        return self._client.vector_stores.search(**payload)

    def _resolve_filename(self, file_id: str) -> str:
        if file_id in self._filename_cache:
            return self._filename_cache[file_id]

        filename = file_id
        try:
            file_object = self._client.files.retrieve(file_id)
            filename = str(getattr(file_object, "filename", file_id))
        except Exception:
            logger.debug(
                "kb_vector_store_filename_lookup_failed file_id=%s",
                file_id,
                exc_info=True,
            )
        self._filename_cache[file_id] = filename
        return filename
