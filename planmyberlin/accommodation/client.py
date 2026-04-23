"""Accommodation suggestions (links only, no booking)."""

from __future__ import annotations

import os
from typing import Any

import httpx


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
    map_points: list[dict[str, Any]] | None = None,
    budget_tier: str,
    party_size: int,
    backend: str = "curated",
    max_items: int = 4,
    city: str = "Berlin",
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    """Return accommodation suggestions with links (no booking)."""
    provider = backend.strip().lower()
    if provider == "google_places":
        api_key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
        if not api_key:
            return {
                "status": "unavailable",
                "backend": provider,
                "message": "GOOGLE_PLACES_API_KEY not set",
                "accommodation_items": [],
            }

        wanted = [str(x).strip() for x in neighbourhoods if str(x).strip()]
        around = [str(p.get("name", "")).strip() for p in (map_points or []) if str(p.get("name", "")).strip()]
        # Itinerary-area first, then neighbourhoods, then generic city search.
        queries: list[str] = []
        for name in around[:4]:
            queries.append(f"hotel near {name}, {city}")
        for area in wanted[:4]:
            queries.append(f"hotel in {area}, {city}")
        if not queries:
            queries.append(f"best hotels in {city}")

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,places.location,"
                "places.rating,places.userRatingCount,places.websiteUri,places.googleMapsUri"
            ),
        }
        out: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                for q in queries:
                    resp = client.post(
                        "https://places.googleapis.com/v1/places:searchText",
                        headers=headers,
                        json={"textQuery": q, "maxResultCount": 5},
                    )
                    resp.raise_for_status()
                    payload = resp.json()
                    places = payload.get("places")
                    if not isinstance(places, list):
                        continue
                    for p in places:
                        if not isinstance(p, dict):
                            continue
                        pid = str(p.get("id", "")).strip()
                        if not pid or pid in seen_ids:
                            continue
                        seen_ids.add(pid)
                        dn = p.get("displayName") if isinstance(p.get("displayName"), dict) else {}
                        name = str(dn.get("text", "")).strip() or "Hotel option"
                        address = str(p.get("formattedAddress", "")).strip()
                        loc = p.get("location") if isinstance(p.get("location"), dict) else {}
                        district = wanted[0] if wanted else city
                        url = str(p.get("websiteUri") or p.get("googleMapsUri") or "").strip()
                        out.append(
                            {
                                "name": name,
                                "district": district,
                                "type": "hotel",
                                "reason": f"Well-reviewed stay option near your planned areas. {address}".strip(),
                                "url": url,
                                "rating": p.get("rating"),
                                "reviews": p.get("userRatingCount"),
                                "address": address,
                                "latitude": loc.get("latitude") if isinstance(loc.get("latitude"), (int, float)) else None,
                                "longitude": loc.get("longitude") if isinstance(loc.get("longitude"), (int, float)) else None,
                                "place_id": pid,
                            }
                        )
            picks = out[: max(1, max_items)]
            return {
                "status": "ok" if picks else "unavailable",
                "backend": provider,
                "message": "Reviews and location from Google Places (no booking)."
                if picks
                else "No accommodation matches found for current trip areas.",
                "accommodation_items": picks,
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "backend": provider,
                "message": f"Google Places accommodation unavailable ({type(exc).__name__})",
                "accommodation_items": [],
            }

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
