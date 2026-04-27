import pytest

from planmyberlin.itinerary.generator import generate_itinerary


def test_itinerary_fallback_without_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    venues = [
        {"name": f"Venue {i}", "category": "places", "district": "Mitte", "summary": "x"}
        for i in range(8)
    ]
    out = generate_itinerary(
        {
            "profile": {
                "days": 2,
                "pace": "balanced",
                "budget_tier": "moderate",
                "party_size": 2,
                "dietary_choice": "Doesn't matter / no preference",
                "mobility_choice": "No specific needs",
            },
            "weather_summary": "Clear sky.",
            "weather_bias": "outdoor_or_mixed",
            "transport_items": [],
            "accommodation_items": [],
            "enriched_items": venues,
        }
    )
    assert out["itinerary_status"] == "fallback"
    assert isinstance(out["itinerary"], dict)
    assert len(out["itinerary"].get("days", [])) == 2
    for day in out["itinerary"].get("days", []):
        slots = [str(a.get("time_of_day", "")) for a in day.get("activities", []) if isinstance(a, dict)]
        assert "morning" in slots
        assert "afternoon" in slots
        assert "evening" in slots
        assert all(
            str(a.get("place_name") or "").strip()
            for a in day.get("activities", [])
            if isinstance(a, dict)
        )
    names_seen = [
        str(a.get("place_name", "")).strip().lower()
        for d in out["itinerary"].get("days", [])
        for a in d.get("activities", [])
        if isinstance(a, dict) and str(a.get("place_name") or "").strip()
    ]
    assert len(names_seen) == len(set(names_seen))


def test_hybrid_fallback_adds_nearby_popular_note_when_local_sparse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = generate_itinerary(
        {
            "profile": {
                "days": 2,
                "pace": "balanced",
                "budget_tier": "moderate",
                "party_size": 2,
                "dietary_choice": "Doesn't matter / no preference",
                "mobility_choice": "No specific needs",
                "neighbourhoods": ["Kreuzberg"],
            },
            "weather_summary": "Clear sky.",
            "weather_bias": "outdoor_or_mixed",
            "transport_items": [],
            "accommodation_items": [],
            "enriched_items": [
                {"name": "Museum Island", "category": "places", "district": "Mitte", "summary": "Museums"},
                {"name": "Zoo Berlin", "category": "places", "district": "Charlottenburg", "summary": "Zoo"},
                {"name": "Brandenburg Gate", "category": "places", "district": "Mitte", "summary": "Landmark"},
            ],
        }
    )
    notes = out["itinerary"].get("practical_notes", [])
    assert any("other parts of berlin were added" in str(n).lower() for n in notes)
