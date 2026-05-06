from __future__ import annotations

from pathlib import Path

from app.core.config import (
    DEFAULT_ANSWER_MODEL,
    DEFAULT_ANSWER_REASONING_EFFORT,
    DEFAULT_QUERY_ROUTER_MODEL,
    DEFAULT_QUERY_ROUTER_REASONING_EFFORT,
    Settings,
)


def test_default_openai_models_and_reasoning_are_explicit() -> None:
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="123456:TEST_TOKEN",
    )

    assert settings.openai_query_router_model == DEFAULT_QUERY_ROUTER_MODEL
    assert settings.openai_query_router_reasoning_effort == DEFAULT_QUERY_ROUTER_REASONING_EFFORT
    assert settings.openai_answer_model == DEFAULT_ANSWER_MODEL
    assert settings.openai_answer_reasoning_effort == DEFAULT_ANSWER_REASONING_EFFORT


def test_empty_reasoning_effort_disables_reasoning_payload() -> None:
    settings = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="123456:TEST_TOKEN",
        OPENAI_QUERY_ROUTER_REASONING_EFFORT="",
        OPENAI_ANSWER_REASONING_EFFORT="",
    )

    assert settings.openai_query_router_reasoning_effort is None
    assert settings.openai_answer_reasoning_effort is None


def test_settings_reads_env_but_not_env_local(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    (tmp_path / ".env.local").write_text(
        "TELEGRAM_BOT_TOKEN=123456:LOCAL\nOPENAI_QUERY_ROUTER_MODEL=local-router\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=123456:ENV\nOPENAI_QUERY_ROUTER_MODEL=env-router\n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.telegram_bot_token.get_secret_value() == "123456:ENV"
    assert settings.openai_query_router_model == "env-router"


def test_env_example_documents_default_models() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert f"OPENAI_QUERY_ROUTER_MODEL={DEFAULT_QUERY_ROUTER_MODEL}" in env_example
    assert (
        f"OPENAI_QUERY_ROUTER_REASONING_EFFORT={DEFAULT_QUERY_ROUTER_REASONING_EFFORT}"
        in env_example
    )
    assert f"OPENAI_ANSWER_MODEL={DEFAULT_ANSWER_MODEL}" in env_example
    assert f"OPENAI_ANSWER_REASONING_EFFORT={DEFAULT_ANSWER_REASONING_EFFORT}" in env_example
