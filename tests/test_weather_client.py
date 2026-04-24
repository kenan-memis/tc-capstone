from planmyberlin.weather.client import fetch_weather_context


def test_weather_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    out = fetch_weather_context(city="Berlin")
    assert out["status"] == "unavailable"
    assert out["bias"] == "unknown"


def test_weather_uses_forecast_for_date_range(monkeypatch):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "test-key")

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "list": [
                    {
                        "dt_txt": "2026-05-10 12:00:00",
                        "weather": [{"main": "Rain", "description": "light rain"}],
                        "main": {"temp": 12.3},
                    }
                ]
            }

    calls: list[str] = []

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, params):
            calls.append(url)
            return _Resp()

    monkeypatch.setattr("planmyberlin.weather.client.httpx.Client", _Client)
    out = fetch_weather_context(
        city="Berlin",
        start_date="2026-05-09",
        end_date="2026-05-11",
    )
    assert out["status"] == "ok"
    assert out["bias"] == "indoor"
    assert "Forecast for 2026-05-09 to 2026-05-11 in Berlin" in out["summary"]
    assert any(u.endswith("/forecast") for u in calls)
