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


def test_events_requests_use_page_size_and_date_range(monkeypatch):
    import planmyberlin.events.client as client

    captured: dict = {}

    class _Mgr:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, _url, params=None):
            captured["params"] = dict(params or {})
            return _DummyResponse({"data": {"events": []}})

    monkeypatch.setattr(client.httpx, "Client", lambda **_kw: _Mgr())
    fetch_events_context(
        city="Berlin",
        start_date="2026-05-25",
        end_date="2026-05-28",
        interests=["Museums & galleries"],
        max_items=4,
    )
    assert captured["params"]["page"] == 1
    assert captured["params"]["pageSize"] >= 30
    assert captured["params"]["startDate"] == "2026-05-25"
    assert captured["params"]["endDate"] == "2026-05-28"
    assert "limit" not in captured["params"]


def test_events_api_v2_attraction_label_without_title(monkeypatch):
    """Real Kulturdaten v2 payloads often omit title; name lives on attractions[].referenceLabel."""
    import planmyberlin.events.client as client

    payload = {
        "success": True,
        "data": {
            "page": 1,
            "pageSize": 30,
            "totalCount": 1,
            "events": [
                {
                    "type": "type.Event",
                    "identifier": "E_TEST",
                    "schedule": {"startDate": "2026-05-20", "startTime": "19:00"},
                    "attractions": [
                        {
                            "referenceLabel": {"de": "Konzert X", "en": "Concert X"},
                        }
                    ],
                    "locations": [{"referenceLabel": {"de": "Theater Y", "en": "Theater Y"}}],
                }
            ],
        },
    }
    monkeypatch.setattr(client.httpx, "Client", lambda **_kw: _DummyClient([_DummyResponse(payload)]))
    out = fetch_events_context(
        city="Berlin",
        start_date="2026-05-19",
        end_date="2026-05-23",
        interests=[],
        max_items=4,
    )
    assert out["status"] == "ok"
    assert len(out["events_items"]) == 1
    assert out["events_items"][0]["name"] == "Concert X"
    assert "Theater Y" in out["events_items"][0]["venue"]


def test_events_do_not_filter_by_interest_tags(monkeypatch):
    """Trip interest labels are not substring-matched against event titles (too strict)."""
    import planmyberlin.events.client as client

    payload = {
        "data": {
            "events": [
                {
                    "title": {"en": "Lake swim day", "de": "Badetag"},
                    "schedule": {"startDate": "2026-05-26", "startTime": "10:00"},
                    "description": {"en": "Outdoor swim in Berlin."},
                    "venue": {"name": "Badesee"},
                }
            ]
        }
    }
    monkeypatch.setattr(client.httpx, "Client", lambda timeout: _DummyClient([_DummyResponse(payload)]))
    out = fetch_events_context(
        city="Berlin",
        start_date="2026-05-24",
        end_date="2026-05-30",
        interests=["Museums & galleries", "Coffee & cafés"],
    )
    assert out["status"] == "ok"
    assert len(out["events_items"]) == 1
    assert out["events_items"][0]["name"] == "Lake swim day"


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
