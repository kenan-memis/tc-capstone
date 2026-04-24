"""Public transport context via transport.rest-compatible endpoints."""

from __future__ import annotations

from typing import Any

import httpx


def _transport_mode(name: str, typ: str) -> str:
    text = f"{name} {typ}".strip().lower()
    if "u-bahn" in text or text.startswith("u ") or " u " in f" {text} ":
        return "u_bahn"
    if "s-bahn" in text or text.startswith("s ") or " s " in f" {text} ":
        return "s_bahn"
    if "bus" in text:
        return "bus"
    if "tram" in text or "straßenbahn" in text or "strassenbahn" in text:
        return "tram"
    return "unknown"


def _mode_rank(mode: str) -> int:
    return {
        "u_bahn": 0,
        "s_bahn": 1,
        "bus": 2,
        "tram": 3,
        "unknown": 9,
    }.get(mode, 9)


def _by_place_summary(items: list[dict[str, Any]], *, limit_per_place: int = 2) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in items:
        place = str(row.get("query", "")).strip() or "Selected area"
        grouped.setdefault(place, []).append(row)

    out: list[dict[str, Any]] = []
    for place, rows in grouped.items():
        rows_sorted = sorted(
            rows,
            key=lambda r: (
                r.get("distance_m") if isinstance(r.get("distance_m"), (int, float)) else 10**9,
                _mode_rank(str(r.get("mode", "unknown"))),
            ),
        )
        top = rows_sorted[: max(1, limit_per_place)]
        out.append(
            {
                "place_name": place,
                "options": top,
                "option_count": len(rows),
                "nearest_distance_m": top[0].get("distance_m") if top else None,
            }
        )
    return out


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
            "transport_by_place": [],
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
                place_name = str(point.get("name", "map_point")).strip() or "map_point"
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
                                "query": place_name,
                                "name": str(row.get("name", "")).strip(),
                                "type": str(row.get("type", "")).strip(),
                                "mode": _transport_mode(
                                    str(row.get("name", "")).strip(),
                                    str(row.get("type", "")).strip(),
                                ),
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
                by_place = _by_place_summary(out, limit_per_place=2)
                return {
                    "status": "ok",
                    "backend": "bvg_rest",
                    "message": "ok",
                    "transport_items": out,
                    "transport_by_place": by_place,
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
                            "mode": _transport_mode(
                                str(row.get("name", "")).strip(),
                                str(row.get("type", "")).strip(),
                            ),
                            "distance_m": None,
                            "latitude": loc.get("latitude") if isinstance(loc.get("latitude"), (int, float)) else None,
                            "longitude": loc.get("longitude") if isinstance(loc.get("longitude"), (int, float)) else None,
                        }
                    )
            if not out:
                for query in (f"Berlin Hbf, {city}", f"Alexanderplatz, {city}", city):
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
                                "mode": _transport_mode(
                                    str(row.get("name", "")).strip(),
                                    str(row.get("type", "")).strip(),
                                ),
                                "distance_m": None,
                                "latitude": loc.get("latitude") if isinstance(loc.get("latitude"), (int, float)) else None,
                                "longitude": loc.get("longitude") if isinstance(loc.get("longitude"), (int, float)) else None,
                            }
                        )
                    if out:
                        break
    except httpx.HTTPStatusError as exc:
        return {
            "status": "unavailable",
            "backend": "bvg_rest",
            "message": f"Transport API HTTP {exc.response.status_code}",
            "transport_items": [],
            "transport_by_place": [],
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "backend": "bvg_rest",
            "message": f"Transport API unavailable ({type(exc).__name__})",
            "transport_items": [],
            "transport_by_place": [],
        }

    if not out:
        return {
            "status": "unavailable",
            "backend": "bvg_rest",
            "message": "No live transport stops were returned for selected places; try nearby areas or rerun.",
            "transport_items": [],
            "transport_by_place": [],
        }
    by_place = _by_place_summary(out, limit_per_place=2)
    return {
        "status": "ok",
        "backend": "bvg_rest",
        "message": "ok",
        "transport_items": out,
        "transport_by_place": by_place,
    }
