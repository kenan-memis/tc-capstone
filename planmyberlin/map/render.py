"""Map rendering utilities (Folium)."""

from __future__ import annotations

from typing import Any

import folium


def _category_color(category: str) -> str:
    c = (category or "").lower()
    if "restaurant" in c:
        return "red"
    if "place" in c:
        return "blue"
    return "green"


def build_preview_map(points: list[dict[str, Any]]) -> folium.Map:
    """Build a marker map from enriched points with `latitude`/`longitude`."""
    valid = [p for p in points if isinstance(p.get("latitude"), (int, float)) and isinstance(p.get("longitude"), (int, float))]

    if valid:
        avg_lat = sum(float(p["latitude"]) for p in valid) / len(valid)
        avg_lng = sum(float(p["longitude"]) for p in valid) / len(valid)
        m = folium.Map(location=[avg_lat, avg_lng], zoom_start=12)
    else:
        # Berlin center fallback
        m = folium.Map(location=[52.52, 13.405], zoom_start=11)

    for p in valid:
        name = str(p.get("name", "Place"))
        category = str(p.get("category", ""))
        district = str(p.get("district", ""))
        summary = str(p.get("summary", ""))
        popup = folium.Popup(
            f"<b>{name}</b><br>{category} | {district}<br>{summary}",
            max_width=320,
        )
        folium.Marker(
            location=[float(p["latitude"]), float(p["longitude"])],
            popup=popup,
            tooltip=name,
            icon=folium.Icon(color=_category_color(category), icon="info-sign"),
        ).add_to(m)

    return m
