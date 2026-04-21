from planmyberlin.places.client import fetch_places_enrichment


def test_places_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    out = fetch_places_enrichment(
        [{"name": "Museum Island", "district": "Mitte", "category": "places", "summary": "x"}]
    )
    assert out["status"] == "unavailable"
    assert out["backend"] == "google_places"
    assert out["enriched_items"] == []


def test_serpapi_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    out = fetch_places_enrichment(
        [{"name": "Museum Island", "district": "Mitte", "category": "places", "summary": "x"}],
        backend="serpapi",
    )
    assert out["status"] == "unavailable"
    assert out["backend"] == "serpapi"
    assert out["enriched_items"] == []
