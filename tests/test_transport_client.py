from planmyberlin.transport.client import fetch_transport_context


def test_transport_unsupported_backend() -> None:
    out = fetch_transport_context(items=[], neighbourhoods=[], backend="unknown")
    assert out["status"] == "unavailable"
    assert out["transport_items"] == []


def test_transport_fallback_seed_query() -> None:
    out = fetch_transport_context(items=[], neighbourhoods=[], timeout_seconds=0.001)
    assert out["backend"] == "bvg_rest"
    assert "transport_items" in out
