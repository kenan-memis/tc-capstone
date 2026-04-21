import pytest

import planmyberlin.graph.workflow as wf
from planmyberlin.graph.workflow import build_planner_graph
from planmyberlin.models.trip_profile import TripProfile


def _base_profile(**kwargs: object) -> dict:
    base = {
        "days": 2,
        "party_size": 2,
        "interest_tags": [],
        "neighbourhoods": [],
        "budget_tier": "moderate",
        "pace": "balanced",
        "dietary_choice": "Doesn't matter / no preference",
        "mobility_choice": "No specific needs",
        "include_accommodation": True,
        "extra_details": "",
    }
    base.update(kwargs)
    return TripProfile.model_validate(base).model_dump()


def test_multi_day_with_accommodation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        wf,
        "fetch_weather_context",
        lambda **_: {
            "status": "ok",
            "summary": "Current weather in Berlin: rain, about 10.0°C.",
            "condition_main": "rain",
            "temperature_c": 10.0,
            "bias": "indoor",
        },
    )
    monkeypatch.setattr(
        wf,
        "fetch_places_enrichment",
        lambda *_, **__: {
            "status": "ok",
            "backend": "serpapi",
            "enriched_items": [
                {
                    "name": "Museum Island",
                    "category": "places",
                    "district": "Mitte",
                    "summary": "UNESCO museum complex",
                    "latitude": 52.5169,
                    "longitude": 13.4010,
                }
            ],
            "message": "ok",
        },
    )
    app = build_planner_graph()
    out = app.invoke({"profile": _base_profile(days=3, include_accommodation=True)})
    assert out["trip_track"] == "multi_day"
    assert out["accommodation_outcome"] == "accommodation"
    assert "multi_day_context" in out["routing_trace"]
    assert "accommodation_suggestions_on" in out["routing_trace"]
    assert out["retrieved_count"] >= 1
    assert out["retrieval_backend"] in {"seed", "chroma"}
    assert out["weather_bias"] == "indoor"
    assert out["places_status"] == "ok"
    assert out["enriched_count"] == 1
    assert out["map_status"] == "ok"
    assert out["map_points_count"] == 1


def test_multi_day_without_accommodation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        wf,
        "fetch_weather_context",
        lambda **_: {
            "status": "ok",
            "summary": "Current weather in Berlin: clear sky, about 21.0°C.",
            "condition_main": "clear",
            "temperature_c": 21.0,
            "bias": "outdoor_or_mixed",
        },
    )
    monkeypatch.setattr(
        wf,
        "fetch_places_enrichment",
        lambda *_, **__: {
            "status": "unavailable",
            "backend": "serpapi",
            "enriched_items": [],
            "message": "SERPAPI_API_KEY not set",
        },
    )
    app = build_planner_graph()
    out = app.invoke({"profile": _base_profile(days=4, include_accommodation=False)})
    assert out["trip_track"] == "multi_day"
    assert out["accommodation_outcome"] == "skip_accommodation"
    assert "accommodation_suggestions_off" in out["routing_trace"]
    assert out["weather_bias"] == "outdoor_or_mixed"
    assert out["places_status"] == "unavailable"
    assert out["map_status"] == "no_coordinates"


def test_single_day_skip_accommodation_by_default_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        wf,
        "fetch_weather_context",
        lambda **_: {
            "status": "unavailable",
            "summary": "Weather unavailable.",
            "condition_main": "unknown",
            "temperature_c": None,
            "bias": "unknown",
        },
    )
    monkeypatch.setattr(
        wf,
        "fetch_places_enrichment",
        lambda *_, **__: {
            "status": "ok",
            "backend": "serpapi",
            "enriched_items": [],
            "message": "ok",
        },
    )
    app = build_planner_graph()
    out = app.invoke({"profile": _base_profile(days=1, include_accommodation=False)})
    assert out["trip_track"] == "single_day"
    assert out["accommodation_outcome"] == "skip_accommodation"
    assert "single_day_context" in out["routing_trace"]
    assert out["weather_bias"] == "unknown"


def test_single_day_with_accommodation_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        wf,
        "fetch_weather_context",
        lambda **_: {
            "status": "ok",
            "summary": "Current weather in Berlin: clouds, about 17.0°C.",
            "condition_main": "clouds",
            "temperature_c": 17.0,
            "bias": "outdoor_or_mixed",
        },
    )
    monkeypatch.setattr(
        wf,
        "fetch_places_enrichment",
        lambda *_, **__: {
            "status": "ok",
            "backend": "serpapi",
            "enriched_items": [],
            "message": "ok",
        },
    )
    app = build_planner_graph()
    out = app.invoke({"profile": _base_profile(days=1, include_accommodation=True)})
    assert out["trip_track"] == "single_day"
    assert out["accommodation_outcome"] == "accommodation"


def test_retrieval_trace_marker_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        wf,
        "fetch_weather_context",
        lambda **_: {
            "status": "ok",
            "summary": "Current weather in Berlin: clear sky, about 20.0°C.",
            "condition_main": "clear",
            "temperature_c": 20.0,
            "bias": "outdoor_or_mixed",
        },
    )
    monkeypatch.setattr(
        wf,
        "fetch_places_enrichment",
        lambda *_, **__: {
            "status": "ok",
            "backend": "serpapi",
            "enriched_items": [],
            "message": "ok",
        },
    )
    app = build_planner_graph()
    out = app.invoke({"profile": _base_profile(days=2)})
    assert any(str(x).endswith(f":{out['retrieved_count']}") for x in out["routing_trace"])
    assert any(str(x).startswith("weather:") for x in out["routing_trace"])
    assert any(str(x).startswith("places:") for x in out["routing_trace"])
    assert any(str(x).startswith("map:") for x in out["routing_trace"])


def test_normalize_requires_profile() -> None:
    app = build_planner_graph()
    with pytest.raises(Exception):
        app.invoke({})


def test_render_stub_prompt() -> None:
    from planmyberlin.prompts.loader import render_prompt

    text = render_prompt("stub_coach", "system")
    assert "PlanMyBerlin" in text
