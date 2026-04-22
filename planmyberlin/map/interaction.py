"""Match itinerary place names to map markers for cross-highlighting."""

from __future__ import annotations

from typing import Any


def normalize_place_label(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def find_matching_point(place_name: str, map_points: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the best map row for an itinerary ``place_name`` (substring / equality on normalized labels)."""
    pn = normalize_place_label(place_name)
    if not pn:
        return None
    exact: dict[str, Any] | None = None
    partial: dict[str, Any] | None = None
    for pt in map_points:
        if not isinstance(pt, dict):
            continue
        mn = normalize_place_label(str(pt.get("name", "")))
        if not mn:
            continue
        if pn == mn:
            exact = pt
            break
        if pn in mn or mn in pn:
            partial = pt
    return exact or partial


def itinerary_places_linked_to_map(
    itinerary: dict[str, Any],
    map_points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Places referenced in the itinerary that resolve to coordinates (deduped, itinerary order).

    Each entry: ``name``, ``days`` (sorted ints), ``latitude``, ``longitude``, ``category``, ``district``, ``summary``.
    """
    seen: set[str] = set()
    linked: list[dict[str, Any]] = []

    for day in itinerary.get("days", []) or []:
        if not isinstance(day, dict):
            continue
        dn = day.get("day_number")
        try:
            day_num = int(dn) if dn is not None else 0
        except (TypeError, ValueError):
            day_num = 0
        for act in day.get("activities", []) or []:
            if not isinstance(act, dict):
                continue
            pn = str(act.get("place_name") or "").strip()
            if not pn:
                continue
            pt = find_matching_point(pn, map_points)
            if pt is None:
                continue
            canon = str(pt.get("name", pn)).strip()
            if canon in seen:
                # Merge day into existing row
                for row in linked:
                    if row["name"] == canon:
                        if day_num and day_num not in row["days"]:
                            row["days"].append(day_num)
                            row["days"].sort()
                        break
                continue
            seen.add(canon)
            linked.append(
                {
                    "name": canon,
                    "days": [day_num] if day_num else [],
                    "latitude": float(pt["latitude"]),
                    "longitude": float(pt["longitude"]),
                    "category": str(pt.get("category", "")),
                    "district": str(pt.get("district", "")),
                    "summary": str(pt.get("summary", "")),
                }
            )

    return linked
