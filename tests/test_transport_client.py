from planmyberlin.transport.client import fetch_transport_context


def test_transport_unsupported_backend() -> None:
    out = fetch_transport_context(items=[], neighbourhoods=[], backend="unknown")
    assert out["status"] == "unavailable"
    assert out["transport_items"] == []
    assert out["transport_by_place"] == []


def test_transport_fallback_seed_query() -> None:
    out = fetch_transport_context(items=[], neighbourhoods=[], timeout_seconds=0.001)
    assert out["backend"] == "bvg_rest"
    assert "transport_items" in out
    assert "transport_by_place" in out


def test_transport_prefers_nearby_lookup(monkeypatch) -> None:
    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return [
                {
                    "name": "U Museumsinsel",
                    "type": "stop",
                    "distance": 180,
                    "location": {"latitude": 52.52, "longitude": 13.40},
                }
            ]

    class _Client:
        def __init__(self, *args, **kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, params=None):  # noqa: ANN001
            assert "/locations/nearby" in url
            return _Resp()

    monkeypatch.setattr("planmyberlin.transport.client.httpx.Client", _Client)
    out = fetch_transport_context(
        items=[],
        neighbourhoods=[],
        map_points=[{"name": "Museum Island", "latitude": 52.5169, "longitude": 13.4010}],
    )
    assert out["status"] == "ok"
    assert len(out["transport_items"]) == 1
    assert out["transport_items"][0]["distance_m"] == 180
    assert out["transport_by_place"][0]["place_name"] == "Museum Island"
