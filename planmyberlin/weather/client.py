"""OpenWeatherMap client for lightweight weather biasing in trip planning."""

from __future__ import annotations

import os
from typing import Any

import httpx


def _bias_from_condition(main: str) -> str:
    lowered = (main or "").strip().lower()
    if lowered in {"rain", "drizzle", "thunderstorm", "snow"}:
        return "indoor"
    return "outdoor_or_mixed"


def fetch_weather_context(*, city: str, units: str = "metric", timeout_seconds: float = 8.0) -> dict[str, Any]:
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

    url = "https://api.openweathermap.org/data/2.5/weather"
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

    weather = (data.get("weather") or [{}])[0]
    main = str(weather.get("main", "")).strip() or "unknown"
    desc = str(weather.get("description", "")).strip() or "no description"
    temp = data.get("main", {}).get("temp")
    temp_value = float(temp) if isinstance(temp, (int, float)) else None
    bias = _bias_from_condition(main)

    if temp_value is None:
        summary = f"Current weather in {city}: {desc}."
    else:
        summary = f"Current weather in {city}: {desc}, about {temp_value:.1f}°C."

    return {
        "status": "ok",
        "summary": summary,
        "condition_main": main.lower(),
        "temperature_c": temp_value,
        "bias": bias,
    }
