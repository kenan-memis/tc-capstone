"""Places enrichment for retrieved place/restaurant candidates."""

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


def _fetch_google_places_enrichment(
    items: list[dict[str, Any]],
    *,
    city: str,
    max_items: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    api_key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not api_key:
        return {
            "status": "unavailable",
            "backend": "google_places",
            "enriched_items": [],
            "message": "GOOGLE_PLACES_API_KEY not set",
        }

    chosen = [dict(x) for x in items[: max(0, max_items)]]
    enriched: list[dict[str, Any]] = []

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.location,places.rating,places.userRatingCount"
        ),
    }
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            for item in chosen:
                name = str(item.get("name", "")).strip()
                district = str(item.get("district", "")).strip()
                if not name:
                    continue
                query = f"{name}, {district}, {city}" if district else f"{name}, {city}"
                resp = client.post(
                    "https://places.googleapis.com/v1/places:searchText",
                    headers=headers,
                    json={"textQuery": query, "maxResultCount": 1},
                )
                resp.raise_for_status()
                payload = resp.json()
                places = payload.get("places")
                first = places[0] if isinstance(places, list) and places else {}
                location = first.get("location", {}) if isinstance(first, dict) else {}

                merged = dict(item)
                merged.update(
                    {
                        "address": first.get("formattedAddress", "") if isinstance(first, dict) else "",
                        "rating": first.get("rating") if isinstance(first, dict) else None,
                        "reviews": first.get("userRatingCount") if isinstance(first, dict) else None,
                        "latitude": location.get("latitude")
                        if isinstance(location.get("latitude"), (int, float))
                        else None,
                        "longitude": location.get("longitude")
                        if isinstance(location.get("longitude"), (int, float))
                        else None,
                        "place_id": first.get("id", "") if isinstance(first, dict) else "",
                    }
                )
                enriched.append(merged)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        details = exc.response.text.strip()
        if len(details) > 300:
            details = f"{details[:300]}..."
        return {
            "status": "unavailable",
            "backend": "google_places",
            "enriched_items": [],
            "message": f"Google Places HTTP {status}: {details}",
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "backend": "google_places",
            "enriched_items": [],
            "message": f"Google Places unavailable ({type(exc).__name__})",
        }

    return {
        "status": "ok",
        "backend": "google_places",
        "enriched_items": enriched,
        "message": "ok",
    }


def _fetch_serpapi_enrichment(
    items: list[dict[str, Any]],
    *,
    city: str,
    max_items: int,
    timeout_seconds: float,
) -> dict[str, Any]:
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


def fetch_places_enrichment(
    items: list[dict[str, Any]],
    *,
    city: str = "Berlin",
    max_items: int = 6,
    timeout_seconds: float = 8.0,
    backend: str = "google_places",
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
    provider = backend.strip().lower()
    if provider == "serpapi":
        return _fetch_serpapi_enrichment(
            items,
            city=city,
            max_items=max_items,
            timeout_seconds=timeout_seconds,
        )

    if provider == "google_places":
        return _fetch_google_places_enrichment(
            items,
            city=city,
            max_items=max_items,
            timeout_seconds=timeout_seconds,
        )

    return {
        "status": "unavailable",
        "backend": provider or "unknown",
        "enriched_items": [],
        "message": f"Unsupported places backend: {backend}",
    }
