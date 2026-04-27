from planmyberlin.events.client import fetch_events_context


class _DummyResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


class _DummyClient:
    def __init__(self, responses):
        self._responses = list(responses)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, _url, params=None):
        _ = params
        if not self._responses:
            raise RuntimeError("no responses")
        return self._responses.pop(0)


def test_events_kulturdaten_ok(monkeypatch):
    import planmyberlin.events.client as client

    payload = {
        "data": {
            "events": [
                {
                    "name": "Berlin Jazz Night",
                    "startDate": "2026-05-02",
                    "venue": {"name": "Kreuzberg Hall"},
                    "url": "https://example.org/jazz",
                    "description": "Live jazz evening in Berlin.",
                    "category": "Music",
                }
            ]
        }
    }
    monkeypatch.setattr(client.httpx, "Client", lambda timeout: _DummyClient([_DummyResponse(payload)]))
    out = fetch_events_context(
        city="Berlin",
        start_date="2026-05-01",
        end_date="2026-05-03",
        interests=["jazz"],
    )
    assert out["status"] == "ok"
    assert out["backend"] == "kulturdaten"
    assert len(out["events_items"]) == 1
    assert out["events_items"][0]["name"] == "Berlin Jazz Night"


def test_events_unavailable_when_all_endpoints_fail(monkeypatch):
    import planmyberlin.events.client as client

    monkeypatch.setattr(
        client.httpx,
        "Client",
        lambda timeout: _DummyClient(
            [
                _DummyResponse({}, 503),
                _DummyResponse({}, 503),
                _DummyResponse({}, 503),
            ]
        ),
    )
    out = fetch_events_context(
        city="Berlin",
        start_date="2026-05-01",
        end_date="2026-05-03",
        interests=[],
    )
    assert out["status"] == "unavailable"
    assert out["events_items"] == []
