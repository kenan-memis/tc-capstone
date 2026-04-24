"""Structured trip preferences — filled from Streamlit and passed into LangGraph."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator, field_validator

from planmyberlin.config.loader import (
    get_dietary_options,
    get_interest_options,
    get_mobility_options,
    get_neighbourhood_options,
)


BudgetTier = Literal["low", "moderate", "high"]
PaceOption = Literal["relaxed", "balanced", "packed"]


class TripProfile(BaseModel):
    """User-facing trip constraints (planner-only; no booking)."""

    days: int = Field(ge=1, le=14, description="Trip length in days")
    start_date: date | None = Field(default=None, description="Trip start date (optional).")
    end_date: date | None = Field(default=None, description="Trip end date (optional).")
    party_size: int = Field(default=2, ge=1, le=20)
    interest_tags: list[str] = Field(
        default_factory=list,
        description="Selected predefined interests (see interest_options.yaml).",
    )
    neighbourhoods: list[str] = Field(
        default_factory=list,
        description="Selected Berlin areas (see neighbourhood_options.yaml).",
    )
    budget_tier: BudgetTier = "moderate"
    pace: PaceOption = "balanced"
    dietary_choice: str = Field(
        description="Single label from dietary_options.yaml (e.g. vegan, vegetarian).",
    )
    mobility_choice: str = Field(
        description="Single label from mobility_options.yaml (walking distance, stairs, accessibility hints).",
    )
    include_accommodation: bool = Field(
        description=(
            "User wants lodging suggestions. UI defaults: on for multi-day, off for single-day "
            "unless the traveler needs an overnight stay."
        ),
    )
    extra_details: str = Field(
        default="",
        description="Only field for free text: allergies, must-sees, anything not covered above.",
    )

    @field_validator("interest_tags", mode="after")
    @classmethod
    def interest_tags_allowed(cls, v: list[str]) -> list[str]:
        allowed = set(get_interest_options())
        unknown = [x for x in v if x not in allowed]
        if unknown:
            raise ValueError(f"Unknown interest tags: {unknown}")
        return v

    @field_validator("neighbourhoods", mode="after")
    @classmethod
    def neighbourhoods_allowed(cls, v: list[str]) -> list[str]:
        allowed = set(get_neighbourhood_options())
        unknown = [x for x in v if x not in allowed]
        if unknown:
            raise ValueError(f"Unknown neighbourhoods: {unknown}")
        return v

    @field_validator("dietary_choice", mode="after")
    @classmethod
    def dietary_allowed(cls, v: str) -> str:
        allowed = set(get_dietary_options())
        if v not in allowed:
            raise ValueError(f"Dietary choice must be one of the predefined options: {v!r}")
        return v

    @field_validator("mobility_choice", mode="after")
    @classmethod
    def mobility_allowed(cls, v: str) -> str:
        allowed = set(get_mobility_options())
        if v not in allowed:
            raise ValueError(f"Mobility choice must be one of the predefined options: {v!r}")
        return v

    @field_validator("extra_details", mode="before")
    @classmethod
    def strip_extra(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def validate_date_range(self) -> "TripProfile":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self
