"""Accommodation suggestions (links only, no booking)."""

from __future__ import annotations

from typing import Any


_CATALOG: list[dict[str, str]] = [
    {
        "name": "Motel One Berlin-Alexanderplatz",
        "district": "Mitte",
        "type": "hotel",
        "reason": "Central base near major sights and transit connections.",
        "url": "https://www.motel-one.com/en/hotels/berlin/hotel-berlin-alexanderplatz/",
    },
    {
        "name": "EastSeven Berlin Hostel",
        "district": "Prenzlauer Berg",
        "type": "hostel",
        "reason": "Budget-friendly stay in a relaxed neighborhood.",
        "url": "https://www.eastseven.de/",
    },
    {
        "name": "Orania.Berlin",
        "district": "Kreuzberg",
        "type": "hotel",
        "reason": "Comfort-focused option close to food and nightlife areas.",
        "url": "https://orania.berlin/",
    },
    {
        "name": "Michelberger Hotel",
        "district": "Friedrichshain",
        "type": "hotel",
        "reason": "Good fit for creative districts and East-side exploration.",
        "url": "https://michelbergerhotel.com/",
    },
    {
        "name": "Hotel Johann",
        "district": "Kreuzberg",
        "type": "hotel",
        "reason": "Smaller, quieter base with good city access.",
        "url": "https://www.hotel-johann.berlin/",
    },
]


def fetch_accommodation_suggestions(
    *,
    neighbourhoods: list[str],
    budget_tier: str,
    party_size: int,
    backend: str = "curated",
    max_items: int = 4,
) -> dict[str, Any]:
    """Return accommodation suggestions with links (no booking)."""
    provider = backend.strip().lower()
    if provider != "curated":
        return {
            "status": "unavailable",
            "backend": provider or "unknown",
            "message": f"Accommodation backend '{backend}' is not implemented yet.",
            "accommodation_items": [],
        }

    wanted = {str(x).strip().lower() for x in neighbourhoods if str(x).strip()}
    scored: list[tuple[int, dict[str, str]]] = []
    for item in _CATALOG:
        score = 0
        if item["district"].strip().lower() in wanted:
            score += 2
        if budget_tier == "low" and item["type"] == "hostel":
            score += 1
        if budget_tier == "high" and item["type"] == "hotel":
            score += 1
        if party_size >= 3 and item["type"] == "hotel":
            score += 1
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    picks = [dict(x[1]) for x in scored[: max(1, max_items)]]
    return {
        "status": "ok",
        "backend": provider,
        "message": "Links only. No booking is performed.",
        "accommodation_items": picks,
    }
