from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import ENV_FILE

DEFAULT_SEARCH_MAX_RESULTS = 3
DEFAULT_SCORE_THRESHOLD = 0.7
MIN_SEARCH_RESULTS = 1
MAX_SEARCH_RESULTS = 3
MIN_SCORE_THRESHOLD = 0.0
MAX_SCORE_THRESHOLD = 1.0


class KnowledgeBaseOpenAISettings(BaseSettings):
    """Settings for knowledge-base vector store sync and search."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    openai_api_key: SecretStr = Field(validation_alias="OPENAI_API_KEY")
    openai_vector_store_id: str = Field(validation_alias="OPENAI_VECTOR_STORE_ID")
    openai_kb_search_max_results: int = Field(
        default=DEFAULT_SEARCH_MAX_RESULTS,
        validation_alias="OPENAI_KB_SEARCH_MAX_RESULTS",
    )
    openai_kb_score_threshold: float = Field(
        default=DEFAULT_SCORE_THRESHOLD,
        validation_alias="OPENAI_KB_SCORE_THRESHOLD",
    )

    @field_validator("openai_vector_store_id")
    @classmethod
    def validate_vector_store_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "OPENAI_VECTOR_STORE_ID must not be empty."
            raise ValueError(msg)
        return normalized

    @field_validator("openai_kb_search_max_results")
    @classmethod
    def clamp_search_max_results(cls, value: int) -> int:
        return clamp_search_max_results(value)

    @field_validator("openai_kb_score_threshold")
    @classmethod
    def clamp_score_threshold(cls, value: float) -> float:
        return clamp_score_threshold(value)


@lru_cache(maxsize=1)
def get_kb_openai_settings() -> KnowledgeBaseOpenAISettings:
    """Return cached settings for KB vector-store operations."""

    return KnowledgeBaseOpenAISettings()


def clamp_search_max_results(value: int) -> int:
    return max(MIN_SEARCH_RESULTS, min(MAX_SEARCH_RESULTS, value))


def clamp_score_threshold(value: float) -> float:
    return max(MIN_SCORE_THRESHOLD, min(MAX_SCORE_THRESHOLD, value))
