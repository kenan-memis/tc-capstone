from planmyberlin.weather.client import fetch_weather_context


def test_weather_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    out = fetch_weather_context(city="Berlin")
    assert out["status"] == "unavailable"
    assert out["bias"] == "unknown"
