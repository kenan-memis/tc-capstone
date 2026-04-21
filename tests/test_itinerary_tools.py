"""Tests for itinerary tool definitions (state-backed, no network)."""

from __future__ import annotations

import json

from planmyberlin.itinerary.tools import build_itinerary_tools


def test_build_itinerary_tools_digest_contents() -> None:
    state = {
        "weather_summary": "Light rain, 9°C.",
        "weather_bias": "indoor",
        "weather_condition_main": "Rain",
        "weather_temperature_c": 9.0,
        "enriched_items": [
            {
                "name": "Museum Island",
                "category": "places",
                "district": "Mitte",
                "summary": "Museum complex",
            }
        ],
        "transport_items": [{"name": "U Museumsinsel", "type": "stop", "query": "Mitte"}],
        "transport_status": "ok",
        "accommodation_items": [
            {"name": "Example Stay", "type": "hotel", "district": "Mitte", "reason": "Central", "url": "https://example.com"}
        ],
        "accommodation_status": "ok",
        "retrieved_citations": ["seed: museums"],
        "retrieval_backend": "seed",
        "retrieved_count": 3,
    }
    tools = build_itinerary_tools(state)
    by_name = {t.name: t for t in tools}

    w = json.loads(by_name["weather_digest"].invoke({}))
    assert w["weather_bias"] == "indoor"
    assert w["temperature_c"] == 9.0

    c = json.loads(by_name["candidate_places_digest"].invoke({"max_items": 5}))
    assert c["count"] == 1
    assert c["candidates"][0]["name"] == "Museum Island"

    t = json.loads(by_name["transport_hints_digest"].invoke({"limit": 5}))
    assert t["count"] == 1
    assert t["suggestions"][0]["name"] == "U Museumsinsel"

    a = json.loads(by_name["accommodation_links_digest"].invoke({"limit": 3}))
    assert a["stays"][0]["has_url"] is True

    r = json.loads(by_name["retrieval_citations_digest"].invoke({"max_citations": 5}))
    assert r["citations"] == ["seed: museums"]
