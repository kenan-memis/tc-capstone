from planmyberlin.events.client import fetch_events_context


def test_events_unavailable_without_api_key(monkeypatch):
    monkeypatch.delenv("TICKETMASTER_API_KEY", raising=False)
    out = fetch_events_context(
        city="Berlin",
        start_date="2026-05-01",
        end_date="2026-05-03",
        interests=["Museums & galleries"],
    )
    assert out["status"] == "unavailable"
    assert out["events_items"] == []
