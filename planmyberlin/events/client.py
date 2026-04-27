"""Berlin events client (Ticketmaster Discovery API)."""

from __future__ import annotations

from datetime import date
import os
from typing import Any

import httpx


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def fetch_events_context(
    *,
    city: str,
    start_date: str | None,
    end_date: str | None,
    interests: list[str] | None = None,
    max_items: int = 4,
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    api_key = os.getenv("TICKETMASTER_API_KEY")
    if not api_key:
        return {
            "status": "unavailable",
            "backend": "ticketmaster",
            "message": "Events unavailable right now.",
            "events_items": [],
        }

    start = _as_date(start_date)
    end = _as_date(end_date)
    params: dict[str, Any] = {
        "apikey": api_key,
        "city": city,
        "size": max(1, min(max_items, 10)),
        "sort": "date,asc",
    }
    if start:
        params["startDateTime"] = f"{start.isoformat()}T00:00:00Z"
    if end:
        params["endDateTime"] = f"{end.isoformat()}T23:59:59Z"
    if interests:
        # Keep broad matching with a simple OR-like keyword string.
        params["keyword"] = " ".join(str(x) for x in interests[:4] if str(x).strip())

    url = "https://app.ticketmaster.com/discovery/v2/events.json"
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        return {
            "status": "unavailable",
            "backend": "ticketmaster",
            "message": "Events unavailable right now.",
            "events_items": [],
        }

    events = payload.get("_embedded", {}).get("events", [])
    if not isinstance(events, list):
        events = []
    out: list[dict[str, Any]] = []
    for row in events[: max(1, min(max_items, 10))]:
        if not isinstance(row, dict):
            continue
        dates = row.get("dates", {}) if isinstance(row.get("dates"), dict) else {}
        start_block = dates.get("start", {}) if isinstance(dates.get("start"), dict) else {}
        venues = (
            row.get("_embedded", {}).get("venues", [])
            if isinstance(row.get("_embedded"), dict)
            else []
        )
        venue = venues[0] if isinstance(venues, list) and venues and isinstance(venues[0], dict) else {}
        images = row.get("images", [])
        image_url = ""
        if isinstance(images, list) and images:
            for img in images:
                if isinstance(img, dict) and str(img.get("url", "")).strip():
                    image_url = str(img["url"]).strip()
                    break
        out.append(
            {
                "name": str(row.get("name", "")).strip(),
                "start_local": str(start_block.get("localDate", "")).strip(),
                "venue": str(venue.get("name", "")).strip(),
                "url": str(row.get("url", "")).strip(),
                "category": "",
                "summary": "Popular Berlin event during your selected dates.",
                "image_url": image_url,
            }
        )

    return {
        "status": "ok",
        "backend": "ticketmaster",
        "message": "ok" if out else "No events found for selected dates.",
        "events_items": out,
    }
