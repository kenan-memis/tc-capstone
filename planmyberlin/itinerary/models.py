"""Structured itinerary output for LLM generation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ItineraryActivity(BaseModel):
    time_of_day: str = Field(description="morning, afternoon, or evening")
    title: str
    description: str
    place_name: str | None = Field(default=None, description="Must match a candidate place name when used")


class ItineraryDay(BaseModel):
    day_number: int = Field(ge=1)
    theme: str
    activities: list[ItineraryActivity]


class TripItinerary(BaseModel):
    title: str
    days: list[ItineraryDay]
    practical_notes: list[str] = Field(default_factory=list)
