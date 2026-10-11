"""Settings loaded from environment variables and the project-root `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/recommender/config.py -> project root. Paths resolve from here, not the cwd.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env may hold vars for other parts (e.g. the UI)
        populate_by_name=True,
    )

    # Groq. The first env name in each AliasChoices is the one .env.example uses.
    # Optional here so tests and ingestion run without a key; the API checks it at startup.
    llm_api_key: SecretStr | None = Field(None, validation_alias=AliasChoices("LLM_API_KEY", "GROQ_API_KEY"))
    llm_model: str = "openai/gpt-oss-20b"
    llm_timeout_s: float = Field(
        30.0, gt=0, le=120, validation_alias=AliasChoices("LLM_TIMEOUT_SECONDS", "LLM_TIMEOUT_S")
    )
    llm_reasoning_effort: Literal["low", "medium", "high"] = "low"
    # Groq counts this whole cap against the tokens-per-minute limit, used or not.
    # An upper limit only: each call asks for what its reply needs (prompt.completion_budget).
    llm_max_completion_tokens: int = Field(1280, ge=64, le=8192)

    # Each candidate costs about 100 prompt tokens against Groq's 8K tokens/minute limit.
    shortlist_size: int = Field(10, ge=1, le=50, validation_alias=AliasChoices("CANDIDATE_CAP", "SHORTLIST_SIZE"))
    data_dir: Path = PROJECT_ROOT / "data"

    @field_validator("llm_api_key", mode="before")
    @classmethod
    def _blank_key_is_missing(cls, v):
        # `LLM_API_KEY=` copied unchanged from .env.example must fail the startup check.
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, v: Path) -> Path:
        return v if v.is_absolute() else PROJECT_ROOT / v


@lru_cache
def get_settings() -> Settings:
    return Settings()
