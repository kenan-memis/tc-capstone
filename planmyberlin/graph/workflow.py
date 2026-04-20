"""LangGraph planner workflow — profile normalization, retrieval, routing, accommodation gate.

Current retrieval is deterministic over curated seed YAML records. Later milestones can
replace it with a vector retriever while keeping the same state contracts.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from planmyberlin.config.loader import get_settings
from planmyberlin.models.trip_profile import TripProfile
from planmyberlin.rag import retrieve_seed_context


class PlannerState(TypedDict, total=False):
    """State passed between nodes. `profile` is a serialized `TripProfile` dict."""

    profile: dict[str, Any]
    trip_track: Literal["multi_day", "single_day"]
    run_accommodation: bool
    routing_trace: list[str]
    accommodation_outcome: Literal["accommodation", "skip_accommodation"]
    retrieved_items: list[dict[str, Any]]
    retrieved_citations: list[str]
    retrieved_count: int


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


def _retrieve_context(state: PlannerState) -> PlannerState:
    out = dict(state)
    raw = out.get("profile")
    if not isinstance(raw, dict):
        raise ValueError("profile must be present before retrieve_context")

    profile = TripProfile.model_validate(raw)
    retrieval_cfg = get_settings().get("retrieval", {})
    limit = int(retrieval_cfg.get("seed_limit", 8))
    payload = retrieve_seed_context(profile, limit=limit)

    out["retrieved_items"] = list(payload.get("items", []))
    out["retrieved_citations"] = list(payload.get("citations", []))
    out["retrieved_count"] = len(out["retrieved_items"])
    trace = list(out.get("routing_trace", []))
    trace.append(f"seed_retrieval:{out['retrieved_count']}")
    out["routing_trace"] = trace
    return out


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
    """Compile planner graph: normalize → retrieve → trip branch → accommodation branch."""
    g = StateGraph(PlannerState)

    g.add_node("normalize_profile", _normalize_profile)
    g.add_node("retrieve_context", _retrieve_context)
    g.add_node("multi_day_track", _multi_day_track)
    g.add_node("single_day_track", _single_day_track)
    g.add_node("merge", _merge_identity)
    g.add_node("accommodation", _with_accommodation)
    g.add_node("skip_accommodation", _skip_accommodation)

    g.add_edge(START, "normalize_profile")
    g.add_edge("normalize_profile", "retrieve_context")
    g.add_conditional_edges(
        "retrieve_context",
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
