import pytest

from planmyberlin.itinerary.generator import generate_itinerary


def test_itinerary_fallback_without_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = generate_itinerary(
        {
            "profile": {"days": 2, "pace": "balanced", "budget_tier": "moderate"},
            "weather_summary": "Clear sky.",
            "weather_bias": "outdoor_or_mixed",
            "transport_items": [],
            "accommodation_items": [],
            "enriched_items": [{"name": "Museum Island", "category": "places", "district": "Mitte", "summary": "Museums"}],
        }
    )
    assert out["itinerary_status"] == "fallback"
    assert isinstance(out["itinerary"], dict)
    assert len(out["itinerary"].get("days", [])) == 2
