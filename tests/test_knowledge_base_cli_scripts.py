from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from app.services.knowledge_base.types_openai import (
    SearchHit,
    SearchResponse,
    SyncFailure,
    SyncReport,
)


def _load_script_module(script_name: str):
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(f"test_{script_name}", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_kb_sync_cli_returns_non_zero_on_failures(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module("kb_sync_vector_store.py")
    report = SyncReport(
        manifest_path=tmp_path / "manifest.json",
        dry_run=False,
        replace=True,
        scanned_count=1,
        selected_count=1,
        failures=[
            SyncFailure(
                operation="upload",
                logical_id="faq",
                markdown_path="a.md",
                error_type="RuntimeError",
                message="boom",
            )
        ],
    )

    class FakeService:
        def sync_from_manifest(self, **kwargs):
            return report

    monkeypatch.setattr(module, "KnowledgeBaseRetrievalService", lambda: FakeService())
    exit_code = module.main(["--manifest", str(tmp_path / "manifest.json")])
    assert exit_code == 1


def test_kb_sync_cli_returns_zero_on_success(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module("kb_sync_vector_store.py")
    report = SyncReport(
        manifest_path=tmp_path / "manifest.json",
        dry_run=False,
        replace=True,
        scanned_count=2,
        selected_count=2,
        uploaded_count=2,
    )

    class FakeService:
        def sync_from_manifest(self, **kwargs):
            return report

    monkeypatch.setattr(module, "KnowledgeBaseRetrievalService", lambda: FakeService())
    exit_code = module.main(["--manifest", str(tmp_path / "manifest.json")])
    assert exit_code == 0


def test_kb_sync_cli_replace_defaults_and_no_replace_flag(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module("kb_sync_vector_store.py")
    report = SyncReport(
        manifest_path=tmp_path / "manifest.json",
        dry_run=False,
        replace=True,
        scanned_count=1,
        selected_count=1,
        uploaded_count=1,
    )
    call_kwargs: list[dict[str, object]] = []

    class FakeService:
        def sync_from_manifest(self, **kwargs):
            call_kwargs.append(kwargs)
            return report

    monkeypatch.setattr(module, "KnowledgeBaseRetrievalService", lambda: FakeService())
    exit_code_default = module.main(["--manifest", str(tmp_path / "manifest.json")])
    assert exit_code_default == 0
    assert call_kwargs[0]["replace"] is True

    exit_code_no_replace = module.main(
        ["--manifest", str(tmp_path / "manifest.json"), "--no-replace"]
    )
    assert exit_code_no_replace == 0
    assert call_kwargs[1]["replace"] is False


def test_kb_smoke_test_cli_returns_zero_when_fallback_triggered(monkeypatch) -> None:
    module = _load_script_module("kb_smoke_test.py")

    class FakeService:
        def __init__(self, settings):
            self.settings = settings

        def search(self, **kwargs):
            return SearchResponse(
                results=[],
                top_score=0.2,
                used_threshold=0.7,
                fallback_triggered=True,
                fallback_message="No relevant information found in the knowledge base.",
            )

    monkeypatch.setattr(
        module,
        "get_kb_openai_settings",
        lambda: SimpleNamespace(openai_kb_score_threshold=0.7),
    )
    monkeypatch.setattr(module, "KnowledgeBaseRetrievalService", FakeService)
    exit_code = module.main(["how to register?"])
    assert exit_code == 0


def test_kb_smoke_test_cli_returns_zero_with_matching_hits(monkeypatch) -> None:
    module = _load_script_module("kb_smoke_test.py")

    class FakeService:
        def __init__(self, settings):
            self.settings = settings

        def search(self, **kwargs):
            return SearchResponse(
                results=[
                    SearchHit(
                        file_id="f1",
                        filename="faq.md",
                        score=0.9,
                        attributes={"logical_id": "faq", "category": "faq"},
                        text="long text",
                    )
                ],
                top_score=0.9,
                used_threshold=0.7,
                fallback_triggered=False,
                fallback_message=None,
            )

    monkeypatch.setattr(
        module,
        "get_kb_openai_settings",
        lambda: SimpleNamespace(openai_kb_score_threshold=0.7),
    )
    monkeypatch.setattr(module, "KnowledgeBaseRetrievalService", FakeService)
    exit_code = module.main(["how to register?"])
    assert exit_code == 0
