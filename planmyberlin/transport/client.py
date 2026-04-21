"""Public transport context via transport.rest-compatible endpoints."""

from __future__ import annotations

from typing import Any

import httpx


def fetch_transport_context(
    *,
    items: list[dict[str, Any]],
    neighbourhoods: list[str],
    map_points: list[dict[str, Any]] | None = None,
    city: str = "Berlin",
    timeout_seconds: float = 8.0,
    backend: str = "bvg_rest",
    base_url: str = "https://v6.bvg.transport.rest",
    max_queries: int = 3,
    results_per_query: int = 2,
    nearby_results: int = 2,
) -> dict[str, Any]:
    """Fetch a few useful transport stops for the current trip context."""
    provider = backend.strip().lower()
    if provider != "bvg_rest":
        return {
            "status": "unavailable",
            "backend": provider or "unknown",
            "message": f"Unsupported transport backend: {backend}",
            "transport_items": [],
        }

    seeds: list[str] = []
    for n in neighbourhoods:
        s = str(n).strip()
        if s:
            seeds.append(f"{s}, {city}")
    for item in items:
        name = str(item.get("name", "")).strip()
        if name:
            seeds.append(f"{name}, {city}")

    deduped: list[str] = []
    seen: set[str] = set()
    for q in seeds:
        k = q.lower()
        if k not in seen:
            deduped.append(q)
            seen.add(k)
        if len(deduped) >= max(1, max_queries):
            break

    if not deduped:
        deduped = [f"Alexanderplatz, {city}"]

    out: list[dict[str, Any]] = []
    nearby_source = map_points or []
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            # Prefer coordinate-first lookup for higher-quality, localized stops.
            for point in nearby_source[: max(1, max_queries)]:
                lat = point.get("latitude")
                lng = point.get("longitude")
                if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
                    continue
                try:
                    resp = client.get(
                        f"{base_url.rstrip('/')}/locations/nearby",
                        params={
                            "latitude": float(lat),
                            "longitude": float(lng),
                            "results": max(1, nearby_results),
                            "stops": "true",
                            "poi": "false",
                            "addresses": "false",
                        },
                    )
                    resp.raise_for_status()
                    payload = resp.json()
                    if not isinstance(payload, list):
                        continue
                    for row in payload:
                        if not isinstance(row, dict):
                            continue
                        loc = row.get("location") if isinstance(row.get("location"), dict) else {}
                        out.append(
                            {
                                "query": str(point.get("name", "map_point")),
                                "name": str(row.get("name", "")).strip(),
                                "type": str(row.get("type", "")).strip(),
                                "distance_m": row.get("distance")
                                if isinstance(row.get("distance"), (int, float))
                                else None,
                                "latitude": loc.get("latitude") if isinstance(loc.get("latitude"), (int, float)) else None,
                                "longitude": loc.get("longitude") if isinstance(loc.get("longitude"), (int, float)) else None,
                            }
                        )
                except Exception:
                    continue

            if out:
                return {
                    "status": "ok",
                    "backend": "bvg_rest",
                    "message": "ok",
                    "transport_items": out,
                }

            # Fallback to text-query lookup when coordinate nearby search is unavailable.
            for query in deduped:
                resp = client.get(
                    f"{base_url.rstrip('/')}/locations",
                    params={
                        "query": query,
                        "results": max(1, results_per_query),
                        "poi": "false",
                        "addresses": "false",
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
                if not isinstance(payload, list):
                    continue
                for row in payload:
                    if not isinstance(row, dict):
                        continue
                    loc = row.get("location") if isinstance(row.get("location"), dict) else {}
                    out.append(
                        {
                            "query": query,
                            "name": str(row.get("name", "")).strip(),
                            "type": str(row.get("type", "")).strip(),
                            "distance_m": None,
                            "latitude": loc.get("latitude") if isinstance(loc.get("latitude"), (int, float)) else None,
                            "longitude": loc.get("longitude") if isinstance(loc.get("longitude"), (int, float)) else None,
                        }
                    )
    except httpx.HTTPStatusError as exc:
        return {
            "status": "unavailable",
            "backend": "bvg_rest",
            "message": f"Transport API HTTP {exc.response.status_code}",
            "transport_items": [],
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "backend": "bvg_rest",
            "message": f"Transport API unavailable ({type(exc).__name__})",
            "transport_items": [],
        }

    return {
        "status": "ok",
        "backend": "bvg_rest",
        "message": "ok",
        "transport_items": out,
    }
