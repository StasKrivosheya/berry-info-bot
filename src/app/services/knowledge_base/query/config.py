from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.constants import ENV_FILE_FALLBACK, ENV_FILE_LOCAL
from app.services.knowledge_base.query.types import (
    QueryInterpretationStage,
    QueryLLMMode,
    QueryStageToggles,
)

DEFAULT_RULES_MIN_CONFIDENCE = 0.85
DEFAULT_LLM_ALLOWED_FOR: tuple[QueryInterpretationStage, ...] = (
    "classifier",
    "scope",
    "planner",
    "retrieval",
)
DEFAULT_LLM_TIMEOUT_SECONDS = 10
DEFAULT_LLM_CACHE_SIZE = 128
DEFAULT_LLM_MAX_RETRIEVAL_VARIANTS = 1


class KnowledgeBaseQuerySettings(BaseSettings):
    """Settings for rules-first query interpretation and optional LLM fallback."""

    model_config = SettingsConfigDict(
        env_file=(ENV_FILE_LOCAL, ENV_FILE_FALLBACK),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    kb_query_llm_mode: QueryLLMMode = Field(
        default="disabled",
        validation_alias="KB_QUERY_LLM_MODE",
    )
    kb_query_llm_allowed_for: Annotated[
        tuple[QueryInterpretationStage, ...],
        NoDecode,
    ] = Field(
        default=DEFAULT_LLM_ALLOWED_FOR,
        validation_alias="KB_QUERY_LLM_ALLOWED_FOR",
    )
    kb_query_rules_min_confidence: float = Field(
        default=DEFAULT_RULES_MIN_CONFIDENCE,
        validation_alias="KB_QUERY_RULES_MIN_CONFIDENCE",
    )
    kb_query_enable_stage_rules: bool = Field(
        default=True,
        validation_alias="KB_QUERY_ENABLE_STAGE_RULES",
    )
    kb_query_enable_stage_scope: bool = Field(
        default=True,
        validation_alias="KB_QUERY_ENABLE_STAGE_SCOPE",
    )
    kb_query_enable_stage_planner: bool = Field(
        default=True,
        validation_alias="KB_QUERY_ENABLE_STAGE_PLANNER",
    )
    kb_query_enable_stage_retrieval: bool = Field(
        default=True,
        validation_alias="KB_QUERY_ENABLE_STAGE_RETRIEVAL",
    )
    kb_query_enable_stage_renderer: bool = Field(
        default=True,
        validation_alias="KB_QUERY_ENABLE_STAGE_RENDERER",
    )
    kb_query_llm_model: str | None = Field(
        default=None,
        validation_alias="KB_QUERY_LLM_MODEL",
    )
    kb_query_llm_timeout_seconds: int = Field(
        default=DEFAULT_LLM_TIMEOUT_SECONDS,
        validation_alias="KB_QUERY_LLM_TIMEOUT_SECONDS",
    )
    kb_query_llm_cache_size: int = Field(
        default=DEFAULT_LLM_CACHE_SIZE,
        validation_alias="KB_QUERY_LLM_CACHE_SIZE",
    )
    kb_query_llm_max_retrieval_variants: int = Field(
        default=DEFAULT_LLM_MAX_RETRIEVAL_VARIANTS,
        validation_alias="KB_QUERY_LLM_MAX_RETRIEVAL_VARIANTS",
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )

    @field_validator("kb_query_llm_allowed_for", mode="before")
    @classmethod
    def normalize_allowed_for(
        cls,
        value: str | tuple[QueryInterpretationStage, ...] | list[str],
    ) -> tuple[QueryInterpretationStage, ...]:
        if isinstance(value, tuple):
            return _normalize_allowed_for(value)
        if isinstance(value, list):
            return _normalize_allowed_for(tuple(value))
        if value is None:
            return DEFAULT_LLM_ALLOWED_FOR

        raw_values = tuple(
            fragment.strip().casefold()
            for fragment in str(value).split(",")
            if fragment.strip()
        )
        return _normalize_allowed_for(raw_values)

    @field_validator("kb_query_rules_min_confidence")
    @classmethod
    def clamp_rules_min_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, value))

    @field_validator("kb_query_llm_timeout_seconds")
    @classmethod
    def clamp_timeout(cls, value: int) -> int:
        return max(1, min(60, value))

    @field_validator("kb_query_llm_cache_size")
    @classmethod
    def clamp_cache_size(cls, value: int) -> int:
        return max(0, min(1024, value))

    @field_validator("kb_query_llm_max_retrieval_variants")
    @classmethod
    def clamp_retrieval_variants(cls, value: int) -> int:
        return max(0, min(3, value))

    @field_validator("kb_query_llm_model")
    @classmethod
    def normalize_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @property
    def stage_toggles(self) -> QueryStageToggles:
        return QueryStageToggles(
            rules_enabled=self.kb_query_enable_stage_rules,
            scope_enabled=self.kb_query_enable_stage_scope,
            planner_enabled=self.kb_query_enable_stage_planner,
            retrieval_enabled=self.kb_query_enable_stage_retrieval,
            renderer_enabled=self.kb_query_enable_stage_renderer,
        )

    @property
    def llm_api_key(self) -> str | None:
        if self.openai_api_key is None:
            return None
        secret = self.openai_api_key.get_secret_value().strip()
        return secret or None


@lru_cache(maxsize=1)
def get_kb_query_settings() -> KnowledgeBaseQuerySettings:
    return KnowledgeBaseQuerySettings()


def _normalize_allowed_for(
    values: tuple[QueryInterpretationStage | str, ...],
) -> tuple[QueryInterpretationStage, ...]:
    allowed: list[QueryInterpretationStage] = []
    known_values = {"classifier", "scope", "planner", "retrieval"}
    for raw_value in values:
        normalized = str(raw_value).strip().casefold()
        if not normalized:
            continue
        if normalized not in known_values:
            msg = (
                "KB_QUERY_LLM_ALLOWED_FOR must contain only "
                "'classifier', 'scope', 'planner', or 'retrieval'."
            )
            raise ValueError(msg)
        stage = normalized
        if stage not in allowed:
            allowed.append(stage)
    return tuple(allowed) or DEFAULT_LLM_ALLOWED_FOR
