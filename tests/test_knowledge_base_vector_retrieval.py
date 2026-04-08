from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.services.knowledge_base.retrieval.config import KnowledgeBaseOpenAISettings
from app.services.knowledge_base.retrieval.service import KnowledgeBaseRetrievalService
from app.services.knowledge_base.retrieval.vector_store import filter_files_by_logical_id
from app.services.knowledge_base.types_openai import (
    DeleteRecordsReport,
    DeleteReport,
    SearchHit,
    SearchResponse,
    UploadResult,
    VectorStoreFileRecord,
)


class FakeVectorStoreClient:
    def __init__(self, files: list[VectorStoreFileRecord] | None = None) -> None:
        self.files = files or []
        self.ensure_called = False
        self.delete_calls: list[dict[str, object]] = []
        self.delete_record_calls: list[dict[str, object]] = []
        self.upload_calls: list[dict[str, object]] = []
        self.search_payloads: list[dict[str, object]] = []

    def ensure_vector_store(self) -> dict[str, str]:
        self.ensure_called = True
        return {"id": "vs_test"}

    def list_vector_store_files(self) -> list[VectorStoreFileRecord]:
        return list(self.files)

    def delete_files_by_logical_id(
        self,
        logical_id: str,
        *,
        existing_files: list[VectorStoreFileRecord] | None = None,
        delete_underlying: bool = True,
        dry_run: bool = False,
    ) -> DeleteReport:
        files = existing_files if existing_files is not None else self.files
        matches = filter_files_by_logical_id(files, logical_id)
        self.delete_calls.append(
            {
                "logical_id": logical_id,
                "dry_run": dry_run,
                "matched": len(matches),
            }
        )
        return DeleteReport(
            logical_id=logical_id,
            matched_count=len(matches),
            deleted_count=len(matches),
            deleted_underlying_count=len(matches) if delete_underlying else 0,
            deleted_file_ids=[item.file_id for item in matches],
        )

    def delete_file_records(
        self,
        records: list[VectorStoreFileRecord],
        *,
        delete_underlying: bool = True,
        dry_run: bool = False,
    ) -> DeleteRecordsReport:
        self.delete_record_calls.append(
            {
                "file_ids": [record.file_id for record in records],
                "dry_run": dry_run,
                "delete_underlying": delete_underlying,
            }
        )
        return DeleteRecordsReport(
            matched_count=len(records),
            deleted_count=len(records),
            deleted_underlying_count=len(records) if delete_underlying else 0,
            deleted_file_ids=[record.file_id for record in records],
        )

    def upload_markdown_file(
        self,
        markdown_path: Path,
        *,
        attributes: dict[str, str | float | bool],
        dry_run: bool = False,
    ) -> UploadResult:
        self.upload_calls.append(
            {
                "markdown_path": markdown_path.as_posix(),
                "logical_id": attributes.get("logical_id"),
                "language": attributes.get("language"),
                "dry_run": dry_run,
            }
        )
        return UploadResult(
            file_id=f"file_{len(self.upload_calls)}",
            filename=markdown_path.name,
            logical_id=str(attributes.get("logical_id", "")),
            dry_run=dry_run,
        )

    def search(
        self,
        *,
        query: str,
        max_num_results: int,
        rewrite_query: bool,
        score_threshold: float,
        filters: dict[str, object] | None = None,
    ) -> SimpleNamespace:
        self.search_payloads.append(
            {
                "query": query,
                "max_num_results": max_num_results,
                "rewrite_query": rewrite_query,
                "score_threshold": score_threshold,
                "filters": filters,
            }
        )
        return SimpleNamespace(
            data=[
                SimpleNamespace(
                    file_id="file_new",
                    filename="faq.md",
                    score=0.83,
                    attributes={"logical_id": "faq", "category": "faq", "language": "uk"},
                    content=[
                        SimpleNamespace(type="text", text="First chunk"),
                        SimpleNamespace(type="text", text="Second chunk"),
                    ],
                )
            ]
        )


class DeleteFailingVectorStoreClient(FakeVectorStoreClient):
    def delete_files_by_logical_id(
        self,
        logical_id: str,
        *,
        existing_files: list[VectorStoreFileRecord] | None = None,
        delete_underlying: bool = True,
        dry_run: bool = False,
    ) -> DeleteReport:
        raise RuntimeError(f"cannot delete {logical_id}")


class UploadFailingVectorStoreClient(FakeVectorStoreClient):
    def upload_markdown_file(
        self,
        markdown_path: Path,
        *,
        attributes: dict[str, str | float | bool],
        dry_run: bool = False,
    ) -> UploadResult:
        raise RuntimeError(f"cannot upload {markdown_path.name}")


def _settings() -> KnowledgeBaseOpenAISettings:
    return KnowledgeBaseOpenAISettings.model_validate(
        {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_VECTOR_STORE_ID": "vs_test",
            "OPENAI_KB_SEARCH_MAX_RESULTS": 3,
            "OPENAI_KB_SCORE_THRESHOLD": 0.7,
        }
    )


def _write_manifest_with_two_docs(tmp_path: Path) -> Path:
    output_dir = tmp_path / "processed"
    markdown_dir = output_dir / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)
    (markdown_dir / "faq--part-01.md").write_text("# FAQ 1\n", encoding="utf-8")
    (markdown_dir / "faq--part-02.md").write_text("# FAQ 2\n", encoding="utf-8")

    manifest = {
        "output_dir": output_dir.as_posix(),
        "entries": [
            {
                "source_file": "01-faq.csv",
                "source_format": "csv",
                "sheet_name": None,
                "sheet_index": None,
                "workbook_file": None,
                "output_md_file": ["markdown/faq--part-01.md", "markdown/faq--part-02.md"],
                "logical_id": "faq",
                "category": "faq",
                "version": "1.0",
                "updated_at_utc": "2026-03-30T00:00:00+00:00",
                "content_hash_sha256": "abc123",
            }
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_filter_files_by_logical_id_matches_exact_value() -> None:
    files = [
        VectorStoreFileRecord(file_id="f1", filename="a.md", attributes={"logical_id": "faq"}),
        VectorStoreFileRecord(file_id="f2", filename="b.md", attributes={"logical_id": "faq-v2"}),
        VectorStoreFileRecord(file_id="f3", filename="c.md", attributes={"logical_id": "FAQ"}),
    ]
    matched = filter_files_by_logical_id(files, "faq")
    assert [item.file_id for item in matched] == ["f1"]


def test_sync_replaces_once_per_logical_id_and_uploads_all_files(tmp_path: Path) -> None:
    manifest_path = _write_manifest_with_two_docs(tmp_path)
    fake_client = FakeVectorStoreClient(
        files=[
            VectorStoreFileRecord(
                file_id="old_1",
                filename="old.md",
                attributes={"logical_id": "faq"},
            ),
            VectorStoreFileRecord(
                file_id="old_2",
                filename="old2.md",
                attributes={"logical_id": "faq"},
            ),
            VectorStoreFileRecord(
                file_id="other",
                filename="other.md",
                attributes={"logical_id": "other"},
            ),
        ]
    )
    service = KnowledgeBaseRetrievalService(vector_store_client=fake_client, settings=_settings())

    report = service.sync_from_manifest(manifest_path=manifest_path, replace=True, dry_run=False)

    assert fake_client.ensure_called
    assert len(fake_client.delete_calls) == 1
    assert fake_client.delete_calls[0]["logical_id"] == "faq"
    assert fake_client.delete_calls[0]["matched"] == 2
    assert len(fake_client.upload_calls) == 2
    assert all(call["language"] == "uk" for call in fake_client.upload_calls)
    assert report.deleted_count == 2
    assert report.uploaded_count == 2
    assert report.failed_count == 0


def test_sync_dry_run_marks_operations_without_mutating(tmp_path: Path) -> None:
    manifest_path = _write_manifest_with_two_docs(tmp_path)
    fake_client = FakeVectorStoreClient(
        files=[
            VectorStoreFileRecord(
                file_id="old_1",
                filename="old.md",
                attributes={"logical_id": "faq"},
            )
        ]
    )
    service = KnowledgeBaseRetrievalService(vector_store_client=fake_client, settings=_settings())

    report = service.sync_from_manifest(manifest_path=manifest_path, replace=True, dry_run=True)

    assert len(fake_client.delete_calls) == 1
    assert fake_client.delete_calls[0]["dry_run"] is True
    assert all(call["dry_run"] is True for call in fake_client.upload_calls)
    assert report.deleted_count == 1
    assert report.uploaded_count == 2
    assert report.failed_count == 0


def test_sync_delete_failures_do_not_inflate_skipped_count(tmp_path: Path) -> None:
    manifest_path = _write_manifest_with_two_docs(tmp_path)
    fake_client = DeleteFailingVectorStoreClient(
        files=[
            VectorStoreFileRecord(
                file_id="old_1",
                filename="old.md",
                attributes={"logical_id": "faq"},
            )
        ]
    )
    service = KnowledgeBaseRetrievalService(vector_store_client=fake_client, settings=_settings())

    report = service.sync_from_manifest(manifest_path=manifest_path, replace=True, dry_run=False)

    assert report.selected_count == 2
    assert report.skipped_count == 0
    assert report.failed_count == 1
    assert report.uploaded_count == 0
    assert report.failures[0].operation == "delete"


def test_sync_upload_failures_do_not_inflate_skipped_count(tmp_path: Path) -> None:
    manifest_path = _write_manifest_with_two_docs(tmp_path)
    fake_client = UploadFailingVectorStoreClient(
        files=[
            VectorStoreFileRecord(
                file_id="old_1",
                filename="old.md",
                attributes={"logical_id": "faq"},
            )
        ]
    )
    service = KnowledgeBaseRetrievalService(vector_store_client=fake_client, settings=_settings())

    report = service.sync_from_manifest(manifest_path=manifest_path, replace=True, dry_run=False)

    assert report.selected_count == 2
    assert report.skipped_count == 0
    assert report.failed_count == 2
    assert report.uploaded_count == 0
    assert all(failure.operation == "upload" for failure in report.failures)


def test_sync_deletes_stale_workbook_records_for_renamed_sheet(tmp_path: Path) -> None:
    output_dir = tmp_path / "processed"
    markdown_dir = output_dir / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)
    (markdown_dir / "book-new-name.md").write_text("# New Name\n", encoding="utf-8")

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "output_dir": output_dir.as_posix(),
                "entries": [
                    {
                        "source_file": "book.xlsx",
                        "source_format": "xlsx",
                        "sheet_name": "New Name",
                        "sheet_index": 1,
                        "workbook_file": "book.xlsx",
                        "output_md_file": ["markdown/book-new-name.md"],
                        "logical_id": "book-new-name",
                        "category": "offers",
                        "version": "1.0",
                        "updated_at_utc": "2026-03-30T00:00:00+00:00",
                        "content_hash_sha256": "hash",
                    }
                ],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )

    fake_client = FakeVectorStoreClient(
        files=[
            VectorStoreFileRecord(
                file_id="stale_sheet",
                filename="book-old-name.md",
                attributes={
                    "logical_id": "book-old-name",
                    "workbook_file": "book.xlsx",
                    "sheet_name": "Old Name",
                    "sheet_index": "1",
                },
            )
        ]
    )
    service = KnowledgeBaseRetrievalService(vector_store_client=fake_client, settings=_settings())

    report = service.sync_from_manifest(manifest_path=manifest_path, replace=True, dry_run=False)

    assert fake_client.delete_record_calls == [
        {
            "file_ids": ["stale_sheet"],
            "dry_run": False,
            "delete_underlying": True,
        }
    ]
    assert report.deleted_count == 1
    assert report.uploaded_count == 1


def test_sync_skips_workbook_stale_cleanup_when_manifest_has_errors(tmp_path: Path) -> None:
    output_dir = tmp_path / "processed"
    markdown_dir = output_dir / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)
    (markdown_dir / "book-offers.md").write_text("# Offers\n", encoding="utf-8")

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "output_dir": output_dir.as_posix(),
                "entries": [
                    {
                        "source_file": "book.xlsx",
                        "source_format": "xlsx",
                        "sheet_name": "Offers",
                        "sheet_index": 1,
                        "workbook_file": "book.xlsx",
                        "output_md_file": ["markdown/book-offers.md"],
                        "logical_id": "book-offers",
                        "category": "offers",
                        "version": "1.0",
                        "updated_at_utc": "2026-03-30T00:00:00+00:00",
                        "content_hash_sha256": "hash",
                    }
                ],
                "errors": [
                    {
                        "source_file": "book.xlsx",
                        "source_format": "xlsx",
                        "sheet_name": "Broken Sheet",
                        "workbook_file": "book.xlsx",
                        "error_type": "OutlineParseError",
                        "message": "ambiguous",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_client = FakeVectorStoreClient(
        files=[
            VectorStoreFileRecord(
                file_id="stale_sheet",
                filename="book-old-name.md",
                attributes={
                    "logical_id": "book-old-name",
                    "workbook_file": "book.xlsx",
                    "sheet_name": "Old Name",
                    "sheet_index": "2",
                },
            )
        ]
    )
    service = KnowledgeBaseRetrievalService(vector_store_client=fake_client, settings=_settings())

    report = service.sync_from_manifest(manifest_path=manifest_path, replace=True, dry_run=False)

    assert fake_client.delete_record_calls == []
    assert report.deleted_count == 0
    assert report.uploaded_count == 1


def test_search_normalizes_results_and_applies_default_language_filter() -> None:
    fake_client = FakeVectorStoreClient()
    service = KnowledgeBaseRetrievalService(vector_store_client=fake_client, settings=_settings())

    response = service.search(query="how to register?")

    assert isinstance(response, SearchResponse)
    assert response.fallback_triggered is False
    assert response.used_threshold == 0.7
    assert response.top_score == 0.83
    assert len(response.results) == 1
    hit = response.results[0]
    assert isinstance(hit, SearchHit)
    assert hit.file_id == "file_new"
    assert hit.filename == "faq.md"
    assert hit.score == 0.83
    assert hit.attributes["logical_id"] == "faq"
    assert "First chunk" in hit.text
    assert "Second chunk" in hit.text
    payload = fake_client.search_payloads[0]
    assert payload["filters"] == {
        "type": "eq",
        "key": "language",
        "value": "uk",
    }
    assert payload["rewrite_query"] is False
    assert payload["max_num_results"] == 3


def test_search_triggers_fallback_when_top_score_below_threshold() -> None:
    fake_client = FakeVectorStoreClient()
    service = KnowledgeBaseRetrievalService(vector_store_client=fake_client, settings=_settings())

    response = service.search(query="how to register?", score_threshold=0.9)

    assert response.fallback_triggered is True
    assert response.top_score == 0.83
    assert response.results == []
    assert response.fallback_message == "No relevant information found in the knowledge base."


def test_search_triggers_fallback_when_no_results() -> None:
    fake_client = FakeVectorStoreClient()

    def empty_search(**kwargs: object):
        fake_client.search_payloads.append(kwargs)
        return SimpleNamespace(data=[])

    fake_client.search = empty_search  # type: ignore[method-assign]
    service = KnowledgeBaseRetrievalService(vector_store_client=fake_client, settings=_settings())

    response = service.search(query="unknown topic")

    assert response.fallback_triggered is True
    assert response.top_score is None
    assert response.results == []
    assert response.fallback_message == "No relevant information found in the knowledge base."


def test_search_allows_rewrite_query_override() -> None:
    fake_client = FakeVectorStoreClient()
    service = KnowledgeBaseRetrievalService(vector_store_client=fake_client, settings=_settings())

    response = service.search(query="how to register?", rewrite_query=True)

    assert response.fallback_triggered is False
    payload = fake_client.search_payloads[0]
    assert payload["rewrite_query"] is True


