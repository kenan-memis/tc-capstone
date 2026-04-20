import pytest

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


def test_multi_day_with_accommodation() -> None:
    app = build_planner_graph()
    out = app.invoke({"profile": _base_profile(days=3, include_accommodation=True)})
    assert out["trip_track"] == "multi_day"
    assert out["accommodation_outcome"] == "accommodation"
    assert "multi_day_context" in out["routing_trace"]
    assert "accommodation_suggestions_on" in out["routing_trace"]
    assert out["retrieved_count"] >= 1
    assert out["retrieval_backend"] in {"seed", "chroma"}


def test_multi_day_without_accommodation() -> None:
    app = build_planner_graph()
    out = app.invoke({"profile": _base_profile(days=4, include_accommodation=False)})
    assert out["trip_track"] == "multi_day"
    assert out["accommodation_outcome"] == "skip_accommodation"
    assert "accommodation_suggestions_off" in out["routing_trace"]


def test_single_day_skip_accommodation_by_default_path() -> None:
    app = build_planner_graph()
    out = app.invoke({"profile": _base_profile(days=1, include_accommodation=False)})
    assert out["trip_track"] == "single_day"
    assert out["accommodation_outcome"] == "skip_accommodation"
    assert "single_day_context" in out["routing_trace"]


def test_single_day_with_accommodation_when_requested() -> None:
    app = build_planner_graph()
    out = app.invoke({"profile": _base_profile(days=1, include_accommodation=True)})
    assert out["trip_track"] == "single_day"
    assert out["accommodation_outcome"] == "accommodation"


def test_retrieval_trace_marker_present() -> None:
    app = build_planner_graph()
    out = app.invoke({"profile": _base_profile(days=2)})
    assert any(str(x).endswith(f":{out['retrieved_count']}") for x in out["routing_trace"])


def test_normalize_requires_profile() -> None:
    app = build_planner_graph()
    with pytest.raises(Exception):
        app.invoke({})


def test_render_stub_prompt() -> None:
    from planmyberlin.prompts.loader import render_prompt

    text = render_prompt("stub_coach", "system")
    assert "PlanMyBerlin" in text
