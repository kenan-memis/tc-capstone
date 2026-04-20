"""LangGraph planner workflow — profile normalization, retrieval, places enrichment, weather bias, routing, accommodation gate."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from planmyberlin.config.loader import get_settings
from planmyberlin.models.trip_profile import TripProfile
from planmyberlin.places import fetch_places_enrichment
from planmyberlin.rag import retrieve_context
from planmyberlin.weather import fetch_weather_context


class PlannerState(TypedDict, total=False):
    profile: dict[str, Any]
    trip_track: Literal["multi_day", "single_day"]
    run_accommodation: bool
    routing_trace: list[str]
    accommodation_outcome: Literal["accommodation", "skip_accommodation"]

    retrieved_items: list[dict[str, Any]]
    retrieved_citations: list[str]
    retrieved_count: int
    retrieval_backend: Literal["seed", "chroma"]
    retrieval_fallback_reason: str

    places_status: Literal["ok", "unavailable"]
    places_backend: str
    places_message: str
    enriched_items: list[dict[str, Any]]
    enriched_count: int

    weather_status: Literal["ok", "unavailable"]
    weather_summary: str
    weather_condition_main: str
    weather_temperature_c: float | None
    weather_bias: Literal["indoor", "outdoor_or_mixed", "unknown"]


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
    payload = retrieve_context(profile, retrieval_cfg=retrieval_cfg)

    out["retrieved_items"] = list(payload.get("items", []))
    out["retrieved_citations"] = list(payload.get("citations", []))
    out["retrieved_count"] = len(out["retrieved_items"])
    out["retrieval_backend"] = str(payload.get("backend", "seed"))  # type: ignore[assignment]
    if payload.get("fallback_reason"):
        out["retrieval_fallback_reason"] = str(payload["fallback_reason"])

    trace = list(out.get("routing_trace", []))
    trace.append(f"{out['retrieval_backend']}_retrieval:{out['retrieved_count']}")
    out["routing_trace"] = trace
    return out


def _enrich_places(state: PlannerState) -> PlannerState:
    out = dict(state)
    cfg = get_settings().get("places", {})
    city = str(cfg.get("city", "Berlin"))
    timeout_seconds = float(cfg.get("timeout_seconds", 8.0))
    max_items = int(cfg.get("max_items", 6))

    payload = fetch_places_enrichment(
        list(out.get("retrieved_items", [])),
        city=city,
        timeout_seconds=timeout_seconds,
        max_items=max_items,
    )

    out["places_status"] = str(payload.get("status", "unavailable"))  # type: ignore[assignment]
    out["places_backend"] = str(payload.get("backend", "serpapi"))
    out["places_message"] = str(payload.get("message", ""))

    enriched_items = list(payload.get("enriched_items", []))
    out["enriched_items"] = enriched_items
    out["enriched_count"] = len(enriched_items)

    trace = list(out.get("routing_trace", []))
    trace.append(f"places:{out['places_status']}:{out['enriched_count']}")
    out["routing_trace"] = trace
    return out


def _fetch_weather(state: PlannerState) -> PlannerState:
    out = dict(state)
    cfg = get_settings().get("weather", {})
    city = str(cfg.get("city", "Berlin"))
    units = str(cfg.get("units", "metric"))
    timeout_seconds = float(cfg.get("timeout_seconds", 8.0))

    payload = fetch_weather_context(city=city, units=units, timeout_seconds=timeout_seconds)
    out["weather_status"] = str(payload.get("status", "unavailable"))  # type: ignore[assignment]
    out["weather_summary"] = str(payload.get("summary", "Weather unavailable."))
    out["weather_condition_main"] = str(payload.get("condition_main", "unknown"))
    out["weather_temperature_c"] = payload.get("temperature_c") if isinstance(payload.get("temperature_c"), (int, float)) else None
    out["weather_bias"] = str(payload.get("bias", "unknown"))  # type: ignore[assignment]

    trace = list(out.get("routing_trace", []))
    trace.append(f"weather:{out['weather_condition_main']}:{out['weather_bias']}")
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
    """Compile planner graph: normalize → retrieve → places → weather → trip branch → accommodation branch."""
    g = StateGraph(PlannerState)

    g.add_node("normalize_profile", _normalize_profile)
    g.add_node("retrieve_context", _retrieve_context)
    g.add_node("enrich_places", _enrich_places)
    g.add_node("fetch_weather", _fetch_weather)
    g.add_node("multi_day_track", _multi_day_track)
    g.add_node("single_day_track", _single_day_track)
    g.add_node("merge", _merge_identity)
    g.add_node("accommodation", _with_accommodation)
    g.add_node("skip_accommodation", _skip_accommodation)

    g.add_edge(START, "normalize_profile")
    g.add_edge("normalize_profile", "retrieve_context")
    g.add_edge("retrieve_context", "enrich_places")
    g.add_edge("enrich_places", "fetch_weather")
    g.add_conditional_edges(
        "fetch_weather",
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
