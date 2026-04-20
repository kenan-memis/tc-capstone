"""SerpApi-based enrichment for retrieved place/restaurant candidates."""

from __future__ import annotations

import os
from typing import Any

import httpx


def _parse_one_result(raw: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    coords = raw.get("gps_coordinates") or {}
    lat = coords.get("latitude") if isinstance(coords, dict) else None
    lng = coords.get("longitude") if isinstance(coords, dict) else None
    return {
        "name": raw.get("title") or raw.get("name") or fallback_name,
        "address": raw.get("address") or "",
        "rating": raw.get("rating"),
        "reviews": raw.get("reviews"),
        "latitude": float(lat) if isinstance(lat, (int, float)) else None,
        "longitude": float(lng) if isinstance(lng, (int, float)) else None,
        "place_id": raw.get("place_id") or raw.get("data_id") or "",
    }


def fetch_places_enrichment(
    items: list[dict[str, Any]],
    *,
    city: str = "Berlin",
    max_items: int = 6,
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    """Enrich top retrieved records with SerpApi Google Maps details.

    Returns:
    {
      status: ok|unavailable,
      backend: serpapi,
      enriched_items: [...],
      message: str,
    }
    """
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return {
            "status": "unavailable",
            "backend": "serpapi",
            "enriched_items": [],
            "message": "SERPAPI_API_KEY not set",
        }

    chosen = [dict(x) for x in items[: max(0, max_items)]]
    enriched: list[dict[str, Any]] = []

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            for item in chosen:
                name = str(item.get("name", "")).strip()
                district = str(item.get("district", "")).strip()
                if not name:
                    continue
                q = f"{name}, {district}, {city}" if district else f"{name}, {city}"
                resp = client.get(
                    "https://serpapi.com/search.json",
                    params={
                        "engine": "google_maps",
                        "q": q,
                        "hl": "en",
                        "api_key": api_key,
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
                local_results = payload.get("local_results")
                first = None
                if isinstance(local_results, list) and local_results:
                    first = local_results[0]
                elif isinstance(local_results, dict):
                    first = local_results

                if isinstance(first, dict):
                    addon = _parse_one_result(first, fallback_name=name)
                else:
                    addon = {
                        "name": name,
                        "address": "",
                        "rating": None,
                        "reviews": None,
                        "latitude": None,
                        "longitude": None,
                        "place_id": "",
                    }

                merged = dict(item)
                merged.update(
                    {
                        "address": addon["address"],
                        "rating": addon["rating"],
                        "reviews": addon["reviews"],
                        "latitude": addon["latitude"],
                        "longitude": addon["longitude"],
                        "place_id": addon["place_id"],
                    }
                )
                enriched.append(merged)
    except Exception as exc:
        return {
            "status": "unavailable",
            "backend": "serpapi",
            "enriched_items": [],
            "message": f"SerpApi unavailable ({type(exc).__name__})",
        }

    return {
        "status": "ok",
        "backend": "serpapi",
        "enriched_items": enriched,
        "message": "ok",
    }
