"""Tests for itinerary ↔ map marker matching."""

from planmyberlin.map.interaction import (
    find_matching_point,
    itinerary_places_linked_to_map,
    normalize_place_label,
)


def test_normalize_place_label() -> None:
    assert normalize_place_label("  Museum   Island  ") == "museum island"


def test_find_matching_point_exact() -> None:
    pts = [{"name": "Museum Island", "latitude": 52.5, "longitude": 13.4}]
    assert find_matching_point("museum island", pts) == pts[0]


def test_itinerary_places_linked_to_map_merges_days() -> None:
    itinerary = {
        "days": [
            {
                "day_number": 1,
                "activities": [{"place_name": "Museum Island", "title": "Visit"}],
            },
            {
                "day_number": 2,
                "activities": [{"place_name": "museum island", "title": "Return"}],
            },
        ]
    }
    map_points = [
        {"name": "Museum Island", "latitude": 52.5169, "longitude": 13.4010, "category": "places", "district": "Mitte"},
    ]
    linked = itinerary_places_linked_to_map(itinerary, map_points)
    assert len(linked) == 1
    assert linked[0]["days"] == [1, 2]
