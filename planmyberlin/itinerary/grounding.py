"""Grounding checks: itinerary venue names must reference candidate places only."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from planmyberlin.itinerary.models import TripItinerary


def _normalize_name(s: str) -> str:
    return " ".join(s.lower().strip().split())


def candidate_name_allowlist(items: list[dict[str, Any]]) -> tuple[set[str], dict[str, str]]:
    """Return normalized names for matching and canonical display strings."""
    allowed_norm: set[str] = set()
    norm_to_canonical: dict[str, str] = {}
    for item in items:
        raw = str(item.get("name", "")).strip()
        if not raw:
            continue
        n = _normalize_name(raw)
        allowed_norm.add(n)
        norm_to_canonical.setdefault(n, raw)
    return allowed_norm, norm_to_canonical


def _place_name_grounded(place_name: str | None, allowed_norm: set[str]) -> bool:
    if place_name is None or not str(place_name).strip():
        return True
    pn = _normalize_name(place_name)
    if pn in allowed_norm:
        return True
    for a in allowed_norm:
        if not a:
            continue
        if a in pn or pn in a:
            return True
    return False


@dataclass
class GroundingViolation:
    day_number: int
    activity_index: int
    place_name: str


def find_grounding_violations(itinerary: TripItinerary, allowed_norm: set[str]) -> list[GroundingViolation]:
    violations: list[GroundingViolation] = []
    for day in itinerary.days:
        for i, act in enumerate(day.activities):
            pn = act.place_name
            if pn is None or not str(pn).strip():
                continue
            if not _place_name_grounded(pn, allowed_norm):
                violations.append(GroundingViolation(day_number=day.day_number, activity_index=i, place_name=str(pn)))
    return violations


def _canonical_for_place_name(place_name: str, allowed_norm: set[str], norm_to_canonical: dict[str, str]) -> str | None:
    pn = _normalize_name(place_name)
    if pn in norm_to_canonical:
        return norm_to_canonical[pn]
    for a in allowed_norm:
        if not a:
            continue
        if a in pn or pn in a:
            return norm_to_canonical.get(a)
    return None


def sanitize_place_names(itinerary: TripItinerary, allowed_norm: set[str], norm_to_canonical: dict[str, str]) -> TripItinerary:
    """Clear non-grounded place_name values; snap fuzzy matches to canonical candidate spelling."""
    data = itinerary.model_dump()
    cleared = 0
    snapped = 0
    for day in data.get("days", []):
        for act in day.get("activities", []):
            pn = act.get("place_name")
            if pn is None or not str(pn).strip():
                continue
            if _place_name_grounded(str(pn), allowed_norm):
                canon = _canonical_for_place_name(str(pn), allowed_norm, norm_to_canonical)
                if canon and str(pn) != canon:
                    act["place_name"] = canon
                    snapped += 1
                continue
            act["place_name"] = None
            cleared += 1
    notes = list(data.get("practical_notes") or [])
    if cleared:
        notes.append(
            f"Some venue links were removed because they did not match the retrieved candidate list ({cleared} adjusted)."
        )
    data["practical_notes"] = notes
    return TripItinerary.model_validate(data)


def itinerary_json_for_repair(itinerary: TripItinerary) -> str:
    return json.dumps(itinerary.model_dump(), ensure_ascii=False, indent=2)
