"""Berlin events client (Kulturdaten public API)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
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
    if name is not None:
        t = _localized_text(name)
        if t:
            return t
    # Kulturdaten API v2: human-readable label on the first attraction.
    attractions = row.get("attractions")
    if isinstance(attractions, list):
        for att in attractions:
            if not isinstance(att, dict):
                continue
            raw = att.get("referenceLabel")
            if raw is not None:
                t = _localized_text(raw)
                if t:
                    return t
    return ""


def _event_description(row: dict) -> str:
    for key in ("description", "summary", "pleaseNote"):
        raw = row.get(key)
        if raw is not None:
            t = _localized_text(raw)
            if t:
                return t
    return ""


def _clock_display_part(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("00:00"):
        return ""
    parts = raw.split(":")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        h, m = int(parts[0]), int(parts[1])
        return f"{h:02d}:{m:02d}"
    return ""


def _time_range_display(schedule: dict[str, Any]) -> str:
    st = _clock_display_part(schedule.get("startTime"))
    et = _clock_display_part(schedule.get("endTime"))
    if st and et:
        return f"{st}–{et}"
    if st:
        return f"Starts {st}"
    return ""


def _admission_hint_en(row: dict[str, Any]) -> str:
    adm = row.get("admission")
    if not isinstance(adm, dict):
        return ""
    tt = str(adm.get("ticketType") or "").lower()
    if "free" in tt or "freeofcharge" in tt.replace("_", ""):
        return "Free admission."
    return ""


def _find_image_url(obj: Any, depth: int = 0) -> str:
    if depth > 5:
        return ""
    if isinstance(obj, str) and obj.startswith("http") and any(
        ext in obj.lower() for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")
    ):
        return obj.strip()
    if isinstance(obj, dict):
        for key in ("url", "src", "href", "thumbnailUrl", "imageUrl", "posterUrl"):
            v = obj.get(key)
            if isinstance(v, str) and v.startswith("http"):
                return v.strip()
        for v in obj.values():
            found = _find_image_url(v, depth + 1)
            if found:
                return found
    if isinstance(obj, list):
        for v in obj:
            found = _find_image_url(v, depth + 1)
            if found:
                return found
    return ""


def _hints_blob(summary: str, venue: str, admission_en: str, category: str) -> str:
    parts = [p for p in (summary.strip(), venue.strip(), admission_en.strip(), category.strip()) if p]
    return " | ".join(parts)[:2000]


def _event_item_date_key(item: dict[str, Any]) -> date | None:
    return _as_date(str(item.get("start_local", "") or "")[:10] or None)


def _pick_events_across_trip_days(
    candidates: list[dict[str, Any]],
    *,
    trip_start: date | None,
    trip_end: date | None,
    max_items: int,
) -> list[dict[str, Any]]:
    """
    Spread results across calendar days in the trip window (round-robin) so a single
    day does not fill the cap when other days have events too.
    """
    cap = max(1, min(max_items, 10))
    if not candidates:
        return []

    if not trip_start or not trip_end or trip_start > trip_end:
        by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
        undated: list[dict[str, Any]] = []
        for it in candidates:
            dk = _event_item_date_key(it)
            if dk:
                by_day[dk].append(it)
            else:
                undated.append(it)
        day_order = sorted(by_day.keys())
        if len(day_order) <= 1:
            return candidates[:cap]
        return _round_robin_days(day_order, by_day, undated, cap)

    # Trip window: one queue per calendar day in range
    day_list: list[date] = []
    d = trip_start
    while d <= trip_end:
        day_list.append(d)
        d = d + timedelta(days=1)

    by_day = {d: [] for d in day_list}
    undated: list[dict[str, Any]] = []
    for it in candidates:
        dk = _event_item_date_key(it)
        if dk and trip_start <= dk <= trip_end and dk in by_day:
            by_day[dk].append(it)
        elif not dk:
            undated.append(it)
        else:
            undated.append(it)

    return _round_robin_days(day_list, by_day, undated, cap)


def _round_robin_days(
    day_order: list[date],
    by_day: dict[date, list[dict[str, Any]]],
    undated: list[dict[str, Any]],
    cap: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    while len(out) < cap:
        added = False
        for d in day_order:
            if len(out) >= cap:
                break
            if by_day.get(d):
                out.append(by_day[d].pop(0))
                added = True
        if not added:
            while len(out) < cap and undated:
                out.append(undated.pop(0))
                added = True
            if not added:
                break
    return out


def fetch_events_context(
    *,
    city: str,
    start_date: str | None,
    end_date: str | None,
    interests: list[str] | None = None,
    max_items: int = 4,
    timeout_seconds: float = 8.0,
    base_url: str = "https://api-v2.kulturdaten.berlin",
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

    candidates: list[dict[str, Any]] = []
    for row in rows:
        name = _event_title(row)
        if not name:
            continue
        venue = (
            _dig(row, ["location", "name"])
            or _dig(row, ["venue", "name"])
            or row.get("locationName")
            or row.get("venue")
            or ""
        )
        if not str(venue).strip():
            locations = row.get("locations")
            if isinstance(locations, list):
                for loc in locations:
                    if not isinstance(loc, dict):
                        continue
                    raw = loc.get("referenceLabel")
                    if raw is not None:
                        venue = _localized_text(raw)
                        break
        venue = str(venue).strip()
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
        sched = row.get("schedule")
        schedule = sched if isinstance(sched, dict) else {}
        time_range_display = _time_range_display(schedule)
        url = str(
            row.get("url") or row.get("link") or row.get("website") or row.get("frontendUrl") or ""
        ).strip()
        category = str(row.get("category") or row.get("genre") or "").strip()
        summary = _event_description(row)
        image_url = str(
            row.get("image") or row.get("image_url") or _dig(row, ["image", "url"]) or ""
        ).strip()
        if not image_url:
            image_url = _find_image_url(row) or ""
        identifier = str(row.get("identifier", "")).strip()
        admission_en = _admission_hint_en(row)
        hints = _hints_blob(summary, venue, admission_en, category)

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

        candidates.append(
            {
                "name": name,
                "start_local": start_local,
                "time_range_display": time_range_display,
                "venue": venue,
                "url": url,
                "category": category,
                "summary": summary or "Cultural event in Berlin during your selected dates.",
                "admission_hint_en": admission_en,
                "hints_blob": hints,
                "image_url": image_url,
                "identifier": identifier,
            }
        )

    out = _pick_events_across_trip_days(
        candidates,
        trip_start=start,
        trip_end=end,
        max_items=max_items,
    )

    message = "ok" if out else "No events found for the selected dates."
    return {
        "status": "ok",
        "backend": "kulturdaten",
        "message": message,
        "events_items": out,
    }
