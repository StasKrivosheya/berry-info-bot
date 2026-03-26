from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import (
    DATABASE_URL_PREFIX,
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
    database_url: str = Field(validation_alias="DATABASE_URL")
    admin_user_ids_raw: str = Field(default="", validation_alias="ADMIN_USER_IDS")

    # Reserved placeholder for future webhook migration; intentionally unused in Phase 1.
    webhook_secret_path: str | None = Field(
        default=None,
        validation_alias="WEBHOOK_SECRET_PATH",
    )

    # Reserved placeholders for future Google integrations.
    google_client_id: str | None = Field(default=None, validation_alias="GOOGLE_CLIENT_ID")
    google_client_secret: str | None = Field(default=None, validation_alias="GOOGLE_CLIENT_SECRET")
    google_project_id: str | None = Field(default=None, validation_alias="GOOGLE_PROJECT_ID")
    google_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith(DATABASE_URL_PREFIX):
            msg = f"DATABASE_URL must start with '{DATABASE_URL_PREFIX}'"
            raise ValueError(msg)
        return value

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings for consistent process-wide configuration."""

    return Settings()
