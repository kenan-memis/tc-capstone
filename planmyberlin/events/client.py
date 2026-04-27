"""Berlin events client (Kulturdaten public API)."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _localized_text(value: Any) -> str:
    """Kulturdaten uses per-language dicts: {\"de\": \"...\", \"en\": \"...\"}."""
    if isinstance(value, dict):
        for key in ("en", "de"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        for raw in value.values():
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return ""
    return str(value or "").strip()


def _event_title(row: dict) -> str:
    title = row.get("title")
    if title is not None:
        t = _localized_text(title)
        if t:
            return t
    name = row.get("name")
    return _localized_text(name) if name is not None else ""


def _event_description(row: dict) -> str:
    for key in ("description", "summary", "pleaseNote"):
        raw = row.get(key)
        if raw is not None:
            t = _localized_text(raw)
            if t:
                return t
    return ""


def fetch_events_context(
    *,
    city: str,
    start_date: str | None,
    end_date: str | None,
    interests: list[str] | None = None,
    max_items: int = 4,
    timeout_seconds: float = 8.0,
    base_url: str = "https://api.kulturdaten.berlin",
) -> dict[str, Any]:
    # `interests` is accepted for API compatibility but not used to filter results:
    # trip interest labels rarely match event text and would hide valid listings.
    _ = interests
    start = _as_date(start_date)
    end = _as_date(end_date)
    base = base_url.rstrip("/")
    endpoints = [f"{base}/api/events", f"{base}/events", f"{base}/api/public/events"]
    # OpenAPI: pageSize + startDate/endDate (not `limit`). Without server-side dates,
    # the API returns arbitrary upcoming pages and local-only filtering yields zero rows.
    page_size = max(30, max_items * 6)
    params: dict[str, Any] = {"page": 1, "pageSize": page_size}
    if start:
        params["startDate"] = start.isoformat()
    if end:
        params["endDate"] = end.isoformat()

    payload: dict[str, Any] | list[Any] | None = None
    last_err = ""
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            for url in endpoints:
                try:
                    resp = client.get(url, params=params)
                    resp.raise_for_status()
                    payload = resp.json()
                    break
                except Exception as exc:
                    last_err = type(exc).__name__
                    continue
    except Exception as exc:
        last_err = type(exc).__name__

    if payload is None:
        return {
            "status": "unavailable",
            "backend": "kulturdaten",
            "message": "Events are temporarily unavailable right now.",
            "events_items": [],
            "debug": last_err,
        }

    def _dig(obj: Any, keys: list[str]) -> Any:
        cur: Any = obj
        for k in keys:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(k)
        return cur

    def _find_items(obj: Any) -> list[dict[str, Any]]:
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
        if not isinstance(obj, dict):
            return []
        for key in ("events", "items", "results", "data"):
            v = obj.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, dict):
                inner = _find_items(v)
                if inner:
                    return inner
        return []

    rows = _find_items(payload)

    out: list[dict[str, Any]] = []
    for row in rows:
        name = _event_title(row)
        if not name:
            continue
        venue = str(
            _dig(row, ["location", "name"])
            or _dig(row, ["venue", "name"])
            or row.get("locationName")
            or row.get("venue")
            or ""
        ).strip()
        start_raw = (
            row.get("startDate")
            or row.get("start_date")
            or row.get("date")
            or _dig(row, ["date", "start"])
            or _dig(row, ["schedule", "startDate"])
            or ""
        )
        start_local = str(start_raw).strip()
        if len(start_local) >= 10 and start_local[4] == "-" and start_local[7] == "-":
            start_local = start_local[:10]
        url = str(
            row.get("url") or row.get("link") or row.get("website") or row.get("frontendUrl") or ""
        ).strip()
        category = str(row.get("category") or row.get("genre") or "").strip()
        summary = _event_description(row)
        image_url = str(
            row.get("image") or row.get("image_url") or _dig(row, ["image", "url"]) or ""
        ).strip()

        if city and city.lower() not in f"{venue} {summary} {name}".lower():
            # Keep Berlin-focused results where metadata allows this check.
            if any(k in row for k in ("city", "town", "region")):
                place = str(row.get("city") or row.get("town") or row.get("region") or "").lower()
                if city.lower() not in place:
                    continue
        if start_local:
            d = _as_date(start_local)
            if d and start and d < start:
                continue
            if d and end and d > end:
                continue

        out.append(
            {
                "name": name,
                "start_local": start_local,
                "venue": venue,
                "url": url,
                "category": category,
                "summary": summary or "Cultural event in Berlin during your selected dates.",
                "image_url": image_url,
            }
        )
        if len(out) >= max(1, min(max_items, 10)):
            break

    message = "ok" if out else "No events found for the selected dates."
    return {
        "status": "ok",
        "backend": "kulturdaten",
        "message": message,
        "events_items": out,
    }
