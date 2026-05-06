from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import (
    DEFAULT_APP_HOST,
    DEFAULT_APP_NAME,
    DEFAULT_APP_PORT,
    DEFAULT_LOG_LEVEL,
    ENV_FILE_FALLBACK,
    ENV_FILE_LOCAL,
)


class Settings(BaseSettings):
    """Single typed configuration object for the entire application."""

    # Local Python runs are expected to use .env.local.
    # .env remains a fallback to keep older local setups working.
    model_config = SettingsConfigDict(
        env_file=(ENV_FILE_LOCAL, ENV_FILE_FALLBACK),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default=DEFAULT_APP_NAME, validation_alias="APP_NAME")
    app_host: str = Field(default=DEFAULT_APP_HOST, validation_alias="APP_HOST")
    app_port: int = Field(default=DEFAULT_APP_PORT, validation_alias="APP_PORT")
    log_level: str = Field(default=DEFAULT_LOG_LEVEL, validation_alias="LOG_LEVEL")

    telegram_bot_token: SecretStr = Field(validation_alias="TELEGRAM_BOT_TOKEN")
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_vector_store_id: str | None = Field(
        default=None,
        validation_alias="OPENAI_VECTOR_STORE_ID",
    )
    openai_query_router_model: str | None = Field(
        default=None,
        validation_alias="OPENAI_QUERY_ROUTER_MODEL",
    )
    openai_query_router_timeout_seconds: int = Field(
        default=10,
        validation_alias="OPENAI_QUERY_ROUTER_TIMEOUT_SECONDS",
    )
    openai_answer_model: str | None = Field(
        default=None,
        validation_alias="OPENAI_ANSWER_MODEL",
    )
    openai_answer_timeout_seconds: int = Field(
        default=10,
        validation_alias="OPENAI_ANSWER_TIMEOUT_SECONDS",
    )
    query_context_ttl_seconds: int = Field(
        default=900,
        validation_alias="QUERY_CONTEXT_TTL_SECONDS",
    )
    kb_manifest_path: Path = Field(
        default=Path("data/knowledge_base/processed/manifest.json"),
        validation_alias="KB_MANIFEST_PATH",
    )
    kb_lexical_index_path: Path = Field(
        default=Path("data/knowledge_base/processed/kb_lexical.sqlite3"),
        validation_alias="KB_LEXICAL_INDEX_PATH",
    )

    @field_validator(
        "openai_query_router_model",
        "openai_answer_model",
        "openai_vector_store_id",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("openai_query_router_timeout_seconds")
    @classmethod
    def clamp_query_router_timeout(cls, value: int) -> int:
        return max(1, min(60, value))

    @field_validator("openai_answer_timeout_seconds")
    @classmethod
    def clamp_answer_timeout(cls, value: int) -> int:
        return max(1, min(60, value))

    @field_validator("query_context_ttl_seconds")
    @classmethod
    def clamp_query_context_ttl(cls, value: int) -> int:
        return max(30, min(24 * 60 * 60, value))

    @property
    def openai_api_key_value(self) -> str | None:
        if self.openai_api_key is None:
            return None
        normalized = self.openai_api_key.get_secret_value().strip()
        return normalized or None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings for consistent process-wide configuration."""

    return Settings()
