"""Profile persistence models for user defaults/preferences."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

BudgetTier = Literal["low", "moderate", "high"]
PaceOption = Literal["relaxed", "balanced", "packed"]


class UserProfileUpsert(BaseModel):
    """Payload used for create/update profile operations."""

    name: str = Field(min_length=1, max_length=80)
    party_size_default: int = Field(default=2, ge=1, le=20)
    interest_tags_default: list[str] = Field(default_factory=list)
    neighbourhoods_default: list[str] = Field(default_factory=list)
    budget_tier_default: BudgetTier = "moderate"
    pace_default: PaceOption = "balanced"
    dietary_choice_default: str = "Doesn't matter / no preference"
    mobility_choice_default: str = "No specific needs"
    include_accommodation_default: bool = True
    extra_details_default: str = ""


class UserProfile(UserProfileUpsert):
    """Stored profile row."""

    id: str
    created_at: datetime
    updated_at: datetime
