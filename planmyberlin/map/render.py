"""Map rendering utilities (Folium)."""

from __future__ import annotations

from typing import Any

import folium

from planmyberlin.map.interaction import normalize_place_label


def _category_color(category: str) -> str:
    c = (category or "").lower()
    if "hotel" in c or "accommodation" in c or "stay" in c:
        return "green"
    if "restaurant" in c:
        # Folium doesn't support pure yellow marker; orange is the closest.
        return "orange"
    if "place" in c:
        return "blue"
    return "blue"


def build_preview_map(
    points: list[dict[str, Any]],
    *,
    highlight_name: str | None = None,
) -> folium.Map:
    """Build a marker map from enriched points with `latitude`/`longitude`.

    ``highlight_name`` matches marker ``name`` (case-insensitive); that marker uses a distinct icon and the map centers on it when possible.
    """
    valid = [p for p in points if isinstance(p.get("latitude"), (int, float)) and isinstance(p.get("longitude"), (int, float))]

    hl = normalize_place_label(highlight_name) if highlight_name else ""
    focused: dict[str, Any] | None = None
    if hl:
        for p in valid:
            if normalize_place_label(str(p.get("name", ""))) == hl:
                focused = p
                break

    if focused:
        m = folium.Map(
            location=[float(focused["latitude"]), float(focused["longitude"])],
            zoom_start=14,
        )
    elif valid:
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
        is_hi = bool(hl) and normalize_place_label(name) == hl
        color = "darkred" if is_hi else _category_color(category)
        folium.Marker(
            location=[float(p["latitude"]), float(p["longitude"])],
            popup=popup,
            tooltip=name,
            icon=folium.Icon(color=color, icon="info-sign"),
        ).add_to(m)

    return m
