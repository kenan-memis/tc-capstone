"""Build/expand raw seed files using Google Places Text Search (New)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any

import httpx
import yaml

from planmyberlin.kb.district_resolver import candidate_matches_area

GOOGLE_PLACES_TEXT_SEARCH = "https://places.googleapis.com/v1/places:searchText"


DEFAULT_DISTRICT_PLAN: dict[str, dict[str, int]] = {
    "Alexanderplatz & Mitte core": {"restaurants": 50, "places": 15},
    "Kreuzberg": {"restaurants": 50, "places": 15},
    "Friedrichshain": {"restaurants": 40, "places": 15},
    "Neukölln": {"restaurants": 40, "places": 12},
    "Prenzlauer Berg": {"restaurants": 40, "places": 12},
    "Charlottenburg": {"restaurants": 35, "places": 12},
    "Schöneberg": {"restaurants": 30, "places": 10},
    "Wedding": {"restaurants": 25, "places": 8},
    "Tiergarten": {"restaurants": 20, "places": 10},
}

def slugify(text: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "_", text.lower())
    return t.strip("_") or "unknown"


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def district_matches_address(district: str, address: str) -> bool:
    """Heuristic district match to keep out-of-area query leaks low."""
    return _norm(district) in _norm(address)


def district_matches_candidate(
    district: str,
    *,
    address: str,
    latitude: float | None,
    longitude: float | None,
) -> bool:
    """Compatibility wrapper for older tests/callers."""
    return candidate_matches_area(
        district,
        address=address,
        latitude=latitude,
        longitude=longitude,
    )


@dataclass
class SeedBuildResult:
    district: str
    places_added: int
    restaurants_added: int
    places_total: int
    restaurants_total: int


def _extract_display_name(raw: dict[str, Any]) -> str:
    dn = raw.get("displayName")
    if isinstance(dn, dict):
        return str(dn.get("text", "")).strip()
    return str(raw.get("name", "")).strip()


def _search_text(
    client: httpx.Client,
    *,
    api_key: str,
    text_query: str,
    max_result_count: int,
) -> list[dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,places.location,"
            "places.primaryType,places.types,places.rating,places.userRatingCount"
        ),
    }
    resp = client.post(
        GOOGLE_PLACES_TEXT_SEARCH,
        headers=headers,
        json={"textQuery": text_query, "maxResultCount": max(1, min(max_result_count, 20))},
    )
    resp.raise_for_status()
    payload = resp.json()
    places = payload.get("places")
    return [x for x in places if isinstance(x, dict)] if isinstance(places, list) else []


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        pid = str(item.get("place_id", "")).strip()
        name = str(item.get("name", "")).strip().lower()
        key = pid or f"name:{name}"
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _existing_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    items = raw.get("items")
    return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []


def _to_place_seed(raw: dict[str, Any], district: str) -> dict[str, Any]:
    name = _extract_display_name(raw)
    address = str(raw.get("formattedAddress", "")).strip()
    primary_type = str(raw.get("primaryType", "")).strip() or "point_of_interest"
    types = [str(t).strip().lower() for t in raw.get("types", []) if str(t).strip()] if isinstance(raw.get("types"), list) else []
    loc = raw.get("location") if isinstance(raw.get("location"), dict) else {}

    summary = address or f"Popular place in {district}, Berlin."
    return {
        "id": f"place.{slugify(district)}.{slugify(name)}",
        "name": name,
        "type": primary_type,
        "tags": list(dict.fromkeys(types[:6])),
        "indoor_outdoor": "mixed",
        "typical_visit_minutes": 90,
        "summary": summary,
        "address": address,
        "rating": raw.get("rating"),
        "reviews": raw.get("userRatingCount"),
        "latitude": loc.get("latitude") if isinstance(loc.get("latitude"), (int, float)) else None,
        "longitude": loc.get("longitude") if isinstance(loc.get("longitude"), (int, float)) else None,
        "place_id": str(raw.get("id", "")).strip(),
        "source_note": f"Google Places seed build ({datetime.now(UTC).date().isoformat()})",
    }


def _food_type(types: list[str]) -> str:
    t = set(types)
    if "bar" in t:
        return "Bar"
    if "cafe" in t:
        return "Cafe"
    return "Restaurant"


def _to_restaurant_seed(raw: dict[str, Any], district: str) -> dict[str, Any]:
    name = _extract_display_name(raw)
    address = str(raw.get("formattedAddress", "")).strip()
    types = [str(t).strip().lower() for t in raw.get("types", []) if str(t).strip()] if isinstance(raw.get("types"), list) else []
    loc = raw.get("location") if isinstance(raw.get("location"), dict) else {}

    return {
        "id": f"restaurant.{slugify(district)}.{slugify(name)}",
        "name": name,
        "type": _food_type(types),
        "cuisine": "mixed",
        "price_level": "$$",
        "tags": list(dict.fromkeys(types[:6])),
        "indoor_outdoor": "mixed",
        "summary": address or f"Food and drink option in {district}, Berlin.",
        "address": address,
        "rating": raw.get("rating"),
        "reviews": raw.get("userRatingCount"),
        "latitude": loc.get("latitude") if isinstance(loc.get("latitude"), (int, float)) else None,
        "longitude": loc.get("longitude") if isinstance(loc.get("longitude"), (int, float)) else None,
        "place_id": str(raw.get("id", "")).strip(),
        "source_note": f"Google Places seed build ({datetime.now(UTC).date().isoformat()})",
    }


def _write_category(path: Path, *, district: str, category: str, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "district": district,
        "category": category,
        "items": items,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def build_seed_for_district(
    *,
    district: str,
    city: str,
    api_key: str,
    output_root: Path,
    restaurants_target: int,
    places_target: int,
    timeout_seconds: float,
) -> SeedBuildResult:
    with httpx.Client(timeout=timeout_seconds) as client:
        places_raw: list[dict[str, Any]] = []
        for q in (
            f"top museums in {district}, {city}",
            f"best attractions in {district}, {city}",
            f"things to do in {district}, {city}",
        ):
            places_raw.extend(_search_text(client, api_key=api_key, text_query=q, max_result_count=20))

        food_raw: list[dict[str, Any]] = []
        for q in (
            f"best restaurants in {district}, {city}",
            f"popular cafes in {district}, {city}",
            f"bars in {district}, {city}",
        ):
            food_raw.extend(_search_text(client, api_key=api_key, text_query=q, max_result_count=20))

    places_filtered = []
    for x in places_raw:
        loc = x.get("location") if isinstance(x.get("location"), dict) else {}
        lat = loc.get("latitude") if isinstance(loc.get("latitude"), (int, float)) else None
        lng = loc.get("longitude") if isinstance(loc.get("longitude"), (int, float)) else None
        if district_matches_candidate(
            district,
            address=str(x.get("formattedAddress", "")),
            latitude=float(lat) if lat is not None else None,
            longitude=float(lng) if lng is not None else None,
        ):
            places_filtered.append(_to_place_seed(x, district))

    food_filtered = []
    for x in food_raw:
        loc = x.get("location") if isinstance(x.get("location"), dict) else {}
        lat = loc.get("latitude") if isinstance(loc.get("latitude"), (int, float)) else None
        lng = loc.get("longitude") if isinstance(loc.get("longitude"), (int, float)) else None
        if district_matches_candidate(
            district,
            address=str(x.get("formattedAddress", "")),
            latitude=float(lat) if lat is not None else None,
            longitude=float(lng) if lng is not None else None,
        ):
            food_filtered.append(_to_restaurant_seed(x, district))

    places_path = output_root / "places" / f"{slugify(district)}.yaml"
    restaurants_path = output_root / "restaurants" / f"{slugify(district)}.yaml"

    existing_places = _existing_items(places_path)
    existing_food = _existing_items(restaurants_path)

    merged_places = _dedupe_items(existing_places + places_filtered)
    merged_food = _dedupe_items(existing_food + food_filtered)

    final_places = merged_places[: max(1, places_target)]
    final_food = merged_food[: max(1, restaurants_target)]

    _write_category(places_path, district=district, category="places", items=final_places)
    _write_category(restaurants_path, district=district, category="restaurants", items=final_food)

    return SeedBuildResult(
        district=district,
        places_added=max(0, len(final_places) - len(existing_places)),
        restaurants_added=max(0, len(final_food) - len(existing_food)),
        places_total=len(final_places),
        restaurants_total=len(final_food),
    )
