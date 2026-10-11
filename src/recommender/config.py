"""Settings loaded from environment variables and the project-root `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/recommender/config.py -> project root. Paths resolve from here, not the cwd.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env may hold vars for other parts (e.g. the UI)
    )

    # Optional here so tests and ingestion run without a key; the API checks it at startup.
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    shortlist_size: int = Field(20, ge=1, le=50)
    data_dir: Path = PROJECT_ROOT / "data"
    llm_timeout_s: float = Field(30.0, gt=0, le=120)

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, v: Path) -> Path:
        return v if v.is_absolute() else PROJECT_ROOT / v


@lru_cache
def get_settings() -> Settings:
    return Settings()
