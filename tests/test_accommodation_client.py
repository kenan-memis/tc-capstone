from planmyberlin.accommodation.client import fetch_accommodation_suggestions


def test_accommodation_suggestions_basic() -> None:
    out = fetch_accommodation_suggestions(
        neighbourhoods=["Kreuzberg"],
        budget_tier="moderate",
        party_size=2,
    )
    assert out["status"] == "ok"
    assert out["backend"] == "curated"
    assert len(out["accommodation_items"]) >= 1
    first = out["accommodation_items"][0]
    assert "name" in first and "url" in first


def test_accommodation_backend_not_implemented() -> None:
    out = fetch_accommodation_suggestions(
        neighbourhoods=["Mitte"],
        budget_tier="moderate",
        party_size=2,
        backend="future_api",
    )
    assert out["status"] == "unavailable"
    assert out["backend"] == "future_api"
    assert out["accommodation_items"] == []


def test_google_places_backend_requires_key(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    out = fetch_accommodation_suggestions(
        neighbourhoods=["Mitte"],
        map_points=[],
        budget_tier="moderate",
        party_size=2,
        backend="google_places",
    )
    assert out["status"] == "unavailable"
    assert out["backend"] == "google_places"
