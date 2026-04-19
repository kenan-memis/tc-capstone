"""LangGraph planner workflow — profile normalization, trip-length routing, accommodation gate.

Later milestones attach RAG, Places, BVG, and synthesis nodes to this skeleton.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from planmyberlin.models.trip_profile import TripProfile


class PlannerState(TypedDict, total=False):
    """State passed between nodes. `profile` is a serialized `TripProfile` dict."""

    profile: dict[str, Any]
    trip_track: Literal["multi_day", "single_day"]
    run_accommodation: bool
    routing_trace: list[str]
    accommodation_outcome: Literal["accommodation", "skip_accommodation"]


def _normalize_profile(state: PlannerState) -> PlannerState:
    raw = state.get("profile")
    if not isinstance(raw, dict):
        raise ValueError("invoke input must include 'profile' with TripProfile fields")
    profile = TripProfile.model_validate(raw)
    days = profile.days
    trip_track: Literal["multi_day", "single_day"] = "multi_day" if days >= 2 else "single_day"
    return {
        "profile": profile.model_dump(),
        "trip_track": trip_track,
        "run_accommodation": profile.include_accommodation,
        "routing_trace": ["normalized"],
    }


def _multi_day_track(state: PlannerState) -> PlannerState:
    out = dict(state)
    trace = list(out.get("routing_trace", []))
    trace.append("multi_day_context")
    out["routing_trace"] = trace
    return out


def _single_day_track(state: PlannerState) -> PlannerState:
    out = dict(state)
    trace = list(out.get("routing_trace", []))
    trace.append("single_day_context")
    out["routing_trace"] = trace
    return out


def _merge_identity(state: PlannerState) -> PlannerState:
    return dict(state)


def _route_stay_length(state: PlannerState) -> Literal["multi_day", "single_day"]:
    tt = state.get("trip_track")
    if tt == "multi_day":
        return "multi_day"
    return "single_day"


def _route_accommodation(state: PlannerState) -> Literal["accommodation", "skip_accommodation"]:
    if state.get("run_accommodation"):
        return "accommodation"
    return "skip_accommodation"


def _with_accommodation(state: PlannerState) -> PlannerState:
    out = dict(state)
    trace = list(out.get("routing_trace", []))
    trace.append("accommodation_suggestions_on")
    out["routing_trace"] = trace
    out["accommodation_outcome"] = "accommodation"
    return out


def _skip_accommodation(state: PlannerState) -> PlannerState:
    out = dict(state)
    trace = list(out.get("routing_trace", []))
    trace.append("accommodation_suggestions_off")
    out["routing_trace"] = trace
    out["accommodation_outcome"] = "skip_accommodation"
    return out


def build_planner_graph():
    """Compile the planner graph: normalize → trip length branch → accommodation branch."""
    g = StateGraph(PlannerState)

    g.add_node("normalize_profile", _normalize_profile)
    g.add_node("multi_day_track", _multi_day_track)
    g.add_node("single_day_track", _single_day_track)
    g.add_node("merge", _merge_identity)
    g.add_node("accommodation", _with_accommodation)
    g.add_node("skip_accommodation", _skip_accommodation)

    g.add_edge(START, "normalize_profile")
    g.add_conditional_edges(
        "normalize_profile",
        _route_stay_length,
        {"multi_day": "multi_day_track", "single_day": "single_day_track"},
    )
    g.add_edge("multi_day_track", "merge")
    g.add_edge("single_day_track", "merge")
    g.add_conditional_edges(
        "merge",
        _route_accommodation,
        {"accommodation": "accommodation", "skip_accommodation": "skip_accommodation"},
    )
    g.add_edge("accommodation", END)
    g.add_edge("skip_accommodation", END)

    return g.compile()
