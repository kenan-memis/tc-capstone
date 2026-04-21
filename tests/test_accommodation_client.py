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
