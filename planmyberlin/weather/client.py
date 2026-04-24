"""OpenWeatherMap client for lightweight weather biasing in trip planning."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import os
from typing import Any

import httpx


def _bias_from_condition(main: str) -> str:
    lowered = (main or "").strip().lower()
    if lowered in {"rain", "drizzle", "thunderstorm", "snow"}:
        return "indoor"
    return "outdoor_or_mixed"


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _pick_forecast_slice(rows: list[dict[str, Any]], target: date) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_delta: float | None = None
    for row in rows:
        dt_txt = str(row.get("dt_txt", "")).strip()
        if not dt_txt:
            continue
        try:
            dt = datetime.fromisoformat(dt_txt.replace(" ", "T"))
        except ValueError:
            continue
        delta = abs((dt.date() - target).days) + abs(dt.hour - 12) / 24.0
        if best is None or (best_delta is not None and delta < best_delta):
            best = row
            best_delta = delta
    return best


def fetch_weather_context(
    *,
    city: str,
    units: str = "metric",
    timeout_seconds: float = 8.0,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Fetch current weather and map to a simple planning bias.

    Returns a dict that is always safe for graph state:
    {
      "status": "ok" | "unavailable",
      "summary": str,
      "condition_main": str,
      "temperature_c": float | None,
      "bias": "indoor" | "outdoor_or_mixed" | "unknown"
    }
    """
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        return {
            "status": "unavailable",
            "summary": "Weather unavailable (OPENWEATHER_API_KEY not set).",
            "condition_main": "unknown",
            "temperature_c": None,
            "bias": "unknown",
        }

    start = _parse_iso_date(start_date)
    end = _parse_iso_date(end_date)
    use_forecast = bool(start and end)

    url = "https://api.openweathermap.org/data/2.5/forecast" if use_forecast else "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": api_key, "units": units}

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        # Keep this user-visible because it helps local setup/debug (e.g., invalid API key).
        detail = ""
        try:
            payload = exc.response.json()
            msg = str(payload.get("message", "")).strip()
            if msg:
                detail = f" {msg}"
        except Exception:
            pass
        return {
            "status": "unavailable",
            "summary": f"Weather unavailable (HTTP {exc.response.status_code}).{detail}",
            "condition_main": "unknown",
            "temperature_c": None,
            "bias": "unknown",
        }
    except Exception as exc:  # network/API issues should not break planning
        return {
            "status": "unavailable",
            "summary": f"Weather unavailable ({type(exc).__name__}).",
            "condition_main": "unknown",
            "temperature_c": None,
            "bias": "unknown",
        }

    target_row: dict[str, Any]
    if use_forecast and start and end:
        target = start + timedelta(days=((end - start).days // 2))
        rows = data.get("list", [])
        if not isinstance(rows, list) or not rows:
            return {
                "status": "unavailable",
                "summary": f"Weather unavailable for selected dates in {city}.",
                "condition_main": "unknown",
                "temperature_c": None,
                "bias": "unknown",
            }
        target_row = _pick_forecast_slice([x for x in rows if isinstance(x, dict)], target) or rows[0]
    else:
        target_row = data

    weather = (target_row.get("weather") or [{}])[0]
    main = str(weather.get("main", "")).strip() or "unknown"
    desc = str(weather.get("description", "")).strip() or "no description"
    temp = target_row.get("main", {}).get("temp") if isinstance(target_row.get("main"), dict) else None
    temp_value = float(temp) if isinstance(temp, (int, float)) else None
    bias = _bias_from_condition(main)

    if use_forecast and start and end:
        label = f"Forecast for {start.isoformat()} to {end.isoformat()} in {city}"
    else:
        label = f"Current weather in {city}"
    if temp_value is None:
        summary = f"{label}: {desc}."
    else:
        summary = f"{label}: {desc}, about {temp_value:.1f}°C."

    return {
        "status": "ok",
        "summary": summary,
        "condition_main": main.lower(),
        "temperature_c": temp_value,
        "bias": bias,
    }
