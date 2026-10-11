"""Request, data, and response models. Validation rules: architecture.md §5.6, edge-case.md §2."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Budget = Literal["low", "medium", "high"]

MAX_CUISINES = 10


class Preferences(BaseModel):
    # Unknown fields are ignored (API-64); strings are stripped.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    location: str = Field(min_length=1, max_length=100)
    budget: Budget | None = None  # None = any budget (API-20)
    cuisine: list[str] = Field(default_factory=list)
    min_rating: float = Field(0.0, ge=0, le=5, allow_inf_nan=False)
    extras: str = Field("", max_length=300)
    top_k: int = Field(5, ge=1, le=10)

    @field_validator("budget", mode="before")
    @classmethod
    def _casefold_budget(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("cuisine", mode="before")
    @classmethod
    def _wrap_single_cuisine(cls, v: Any) -> Any:
        if v is None:
            return []
        return [v] if isinstance(v, str) else v

    @field_validator("cuisine")
    @classmethod
    def _clean_cuisines(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in v:
            key = item.strip().casefold()
            if key and key not in seen:
                seen.add(key)
                out.append(item.strip())
        if len(out) > MAX_CUISINES:
            raise ValueError(f"at most {MAX_CUISINES} cuisines")
        return out

    @field_validator("extras", mode="before")
    @classmethod
    def _blank_extras(cls, v: Any) -> Any:
        # Whitespace- or punctuation-only extras carry no preference (API-53).
        if v is None:
            return ""
        if isinstance(v, str) and not any(ch.isalnum() for ch in v):
            return ""
        return v


class Restaurant(BaseModel):
    """One cleaned dataset row (architecture.md §5.1)."""

    id: str
    name: str
    city: str
    locality: str | None = None
    cuisines: list[str] = Field(default_factory=list)
    cost_for_two: int | None = Field(None, ge=0)
    budget_tier: Budget | None = None
    rating: float | None = Field(None, ge=0, le=5)
    votes: int = Field(0, ge=0)
    tags: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    rank: int = Field(ge=1)
    id: str
    name: str
    cuisine: list[str]
    rating: float | None
    estimated_cost: int | None
    explanation: str


class RecommendationResponse(BaseModel):
    summary: str = ""
    recommendations: list[Recommendation] = Field(default_factory=list)
    relaxed_constraints: list[str] = Field(default_factory=list)
    llm_fallback: bool = False
    # Why results are empty or fewer than asked (architecture.md §5.4).
    message: str | None = None
