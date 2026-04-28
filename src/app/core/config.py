from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import (
    DEFAULT_APP_HOST,
    DEFAULT_APP_NAME,
    DEFAULT_APP_PORT,
    DEFAULT_DEBUG_COMMANDS_MODE,
    DEFAULT_LOG_LEVEL,
    ENV_FILE_FALLBACK,
    ENV_FILE_LOCAL,
)

DebugCommandsMode = Literal["disabled", "admins", "public"]


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
    debug_commands_mode: DebugCommandsMode = Field(
        default=DEFAULT_DEBUG_COMMANDS_MODE,
        validation_alias="DEBUG_COMMANDS_MODE",
    )

    telegram_bot_token: SecretStr = Field(validation_alias="TELEGRAM_BOT_TOKEN")
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
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
    admin_user_ids_raw: str = Field(default="", validation_alias="ADMIN_USER_IDS")

    @field_validator("debug_commands_mode", mode="before")
    @classmethod
    def validate_debug_commands_mode(cls, value: object) -> DebugCommandsMode:
        normalized = str(value or DEFAULT_DEBUG_COMMANDS_MODE).strip().casefold()
        if normalized in {"disabled", "admins", "public"}:
            return normalized  # type: ignore[return-value]

        msg = "DEBUG_COMMANDS_MODE must be one of: disabled, admins, public."
        raise ValueError(msg)

    @field_validator("openai_query_router_model")
    @classmethod
    def normalize_query_router_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("openai_answer_model")
    @classmethod
    def normalize_answer_model(cls, value: str | None) -> str | None:
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
    def admin_user_ids(self) -> tuple[int, ...]:
        # ADMIN_USER_IDS is stored as CSV in env to stay easy to configure in Docker and CI.
        # We parse and expose it as typed integers so downstream code can use it safely.
        if not self.admin_user_ids_raw.strip():
            return ()

        parsed_ids: list[int] = []
        for raw_value in self.admin_user_ids_raw.split(","):
            stripped = raw_value.strip()
            if not stripped:
                continue
            try:
                parsed_ids.append(int(stripped))
            except ValueError as exc:
                msg = "ADMIN_USER_IDS must be a comma-separated list of integers."
                raise ValueError(msg) from exc
        return tuple(parsed_ids)

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
