"""LangGraph planner workflow — profile normalization, retrieval, places enrichment, weather bias, map points, routing, accommodation gate."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from planmyberlin.accommodation import fetch_accommodation_suggestions
from planmyberlin.config.loader import get_settings
from planmyberlin.itinerary import generate_itinerary
from planmyberlin.observability import get_logger
from planmyberlin.models.trip_profile import TripProfile
from planmyberlin.places import fetch_places_enrichment
from planmyberlin.rag import retrieve_context
from planmyberlin.transport import fetch_transport_context
from planmyberlin.weather import fetch_weather_context

_log = get_logger(__name__)


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

    map_status: Literal["ok", "no_coordinates"]
    map_points: list[dict[str, Any]]
    map_points_count: int

    transport_status: Literal["ok", "unavailable"]
    transport_backend: str
    transport_message: str
    transport_items: list[dict[str, Any]]
    transport_count: int

    accommodation_status: Literal["ok", "unavailable"]
    accommodation_backend: str
    accommodation_message: str
    accommodation_items: list[dict[str, Any]]
    accommodation_count: int

    itinerary_status: Literal["ok", "ok_repaired", "grounded_sanitized", "fallback", "unavailable"]
    itinerary: dict[str, Any]
    itinerary_message: str


def _normalize_profile(state: PlannerState) -> PlannerState:
    raw = state.get("profile")
    if not isinstance(raw, dict):
        raise ValueError("invoke input must include 'profile' with TripProfile fields")
    profile = TripProfile.model_validate(raw)
    days = profile.days
    trip_track: Literal["multi_day", "single_day"] = "multi_day" if days >= 2 else "single_day"
    _log.info(
        "graph node=normalize_profile trip_track=%s days=%d accommodation_requested=%s",
        trip_track,
        days,
        profile.include_accommodation,
    )
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
    _log.info(
        "graph node=retrieve_context backend=%s items=%d fallback=%s",
        out["retrieval_backend"],
        out["retrieved_count"],
        bool(out.get("retrieval_fallback_reason")),
    )
    return out


def _enrich_places(state: PlannerState) -> PlannerState:
    out = dict(state)
    cfg = get_settings().get("places", {})
    backend = str(cfg.get("backend", "google_places"))
    city = str(cfg.get("city", "Berlin"))
    timeout_seconds = float(cfg.get("timeout_seconds", 8.0))
    max_items = int(cfg.get("max_items", 6))

    payload = fetch_places_enrichment(
        list(out.get("retrieved_items", [])),
        backend=backend,
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
    _log.info(
        "graph node=enrich_places backend=%s status=%s enriched=%d",
        out["places_backend"],
        out["places_status"],
        out["enriched_count"],
    )
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
    _log.info(
        "graph node=fetch_weather status=%s bias=%s temp_c=%s",
        out["weather_status"],
        out["weather_bias"],
        out["weather_temperature_c"],
    )
    return out


def _build_map_points(state: PlannerState) -> PlannerState:
    out = dict(state)
    source = list(out.get("enriched_items", [])) or list(out.get("retrieved_items", []))

    points: list[dict[str, Any]] = []
    for item in source:
        lat = item.get("latitude")
        lng = item.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            points.append(
                {
                    "name": item.get("name", ""),
                    "category": item.get("category", ""),
                    "district": item.get("district", ""),
                    "summary": item.get("summary", ""),
                    "latitude": float(lat),
                    "longitude": float(lng),
                }
            )

    out["map_points"] = points
    out["map_points_count"] = len(points)
    out["map_status"] = "ok" if points else "no_coordinates"

    trace = list(out.get("routing_trace", []))
    trace.append(f"map:{out['map_status']}:{out['map_points_count']}")
    out["routing_trace"] = trace
    _log.info(
        "graph node=build_map_points status=%s markers=%d",
        out["map_status"],
        out["map_points_count"],
    )
    return out


def _fetch_transport(state: PlannerState) -> PlannerState:
    out = dict(state)
    cfg = get_settings().get("transport", {})
    backend = str(cfg.get("backend", "bvg_rest"))
    city = str(cfg.get("city", "Berlin"))
    timeout_seconds = float(cfg.get("timeout_seconds", 8.0))
    base_url = str(cfg.get("base_url", "https://v6.bvg.transport.rest"))
    max_queries = int(cfg.get("max_queries", 3))
    results_per_query = int(cfg.get("results_per_query", 2))
    nearby_results = int(cfg.get("nearby_results", 2))

    profile = out.get("profile", {})
    neighbourhoods = profile.get("neighbourhoods", []) if isinstance(profile, dict) else []
    payload = fetch_transport_context(
        items=list(out.get("enriched_items", [])) or list(out.get("retrieved_items", [])),
        neighbourhoods=list(neighbourhoods) if isinstance(neighbourhoods, list) else [],
        map_points=list(out.get("map_points", [])),
        city=city,
        timeout_seconds=timeout_seconds,
        backend=backend,
        base_url=base_url,
        max_queries=max_queries,
        results_per_query=results_per_query,
        nearby_results=nearby_results,
    )

    out["transport_status"] = str(payload.get("status", "unavailable"))  # type: ignore[assignment]
    out["transport_backend"] = str(payload.get("backend", backend))
    out["transport_message"] = str(payload.get("message", ""))
    items = list(payload.get("transport_items", []))
    out["transport_items"] = items
    out["transport_count"] = len(items)

    trace = list(out.get("routing_trace", []))
    trace.append(f"transport:{out['transport_status']}:{out['transport_count']}")
    out["routing_trace"] = trace
    _log.info(
        "graph node=fetch_transport backend=%s status=%s suggestions=%d",
        out["transport_backend"],
        out["transport_status"],
        out["transport_count"],
    )
    return out


def _multi_day_track(state: PlannerState) -> PlannerState:
    out = dict(state)
    trace = list(out.get("routing_trace", []))
    trace.append("multi_day_context")
    out["routing_trace"] = trace
    _log.info("graph node=multi_day_track")
    return out


def _single_day_track(state: PlannerState) -> PlannerState:
    out = dict(state)
    trace = list(out.get("routing_trace", []))
    trace.append("single_day_context")
    out["routing_trace"] = trace
    _log.info("graph node=single_day_track")
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
    cfg = get_settings().get("accommodation", {})
    backend = str(cfg.get("backend", "curated"))
    max_items = int(cfg.get("max_items", 4))
    profile = out.get("profile", {})
    neighbourhoods = profile.get("neighbourhoods", []) if isinstance(profile, dict) else []
    budget_tier = str(profile.get("budget_tier", "moderate")) if isinstance(profile, dict) else "moderate"
    party_size = int(profile.get("party_size", 2)) if isinstance(profile, dict) else 2

    payload = fetch_accommodation_suggestions(
        neighbourhoods=list(neighbourhoods) if isinstance(neighbourhoods, list) else [],
        budget_tier=budget_tier,
        party_size=party_size,
        backend=backend,
        max_items=max_items,
    )

    out["accommodation_status"] = str(payload.get("status", "unavailable"))  # type: ignore[assignment]
    out["accommodation_backend"] = str(payload.get("backend", "curated"))
    out["accommodation_message"] = str(payload.get("message", ""))
    items = list(payload.get("accommodation_items", []))
    out["accommodation_items"] = items
    out["accommodation_count"] = len(items)

    trace = list(out.get("routing_trace", []))
    trace.append(f"accommodation_suggestions_on:{out['accommodation_count']}")
    out["routing_trace"] = trace
    out["accommodation_outcome"] = "accommodation"
    _log.info(
        "graph node=accommodation backend=%s status=%s suggestions=%d",
        out["accommodation_backend"],
        out["accommodation_status"],
        out["accommodation_count"],
    )
    return out


def _skip_accommodation(state: PlannerState) -> PlannerState:
    out = dict(state)
    trace = list(out.get("routing_trace", []))
    trace.append("accommodation_suggestions_off")
    out["routing_trace"] = trace
    out["accommodation_outcome"] = "skip_accommodation"
    out["accommodation_status"] = "unavailable"
    out["accommodation_backend"] = "curated"
    out["accommodation_message"] = "Accommodation suggestions were skipped by preference."
    out["accommodation_items"] = []
    out["accommodation_count"] = 0
    _log.info("graph node=skip_accommodation")
    return out


def _generate_itinerary(state: PlannerState) -> PlannerState:
    out = dict(state)
    payload = generate_itinerary(out)
    out["itinerary_status"] = str(payload.get("itinerary_status", "unavailable"))  # type: ignore[assignment]
    out["itinerary"] = payload.get("itinerary", {}) if isinstance(payload.get("itinerary"), dict) else {}
    out["itinerary_message"] = str(payload.get("itinerary_message", ""))

    trace = list(out.get("routing_trace", []))
    days = len(out.get("itinerary", {}).get("days", [])) if isinstance(out.get("itinerary"), dict) else 0
    trace.append(f"itinerary:{out['itinerary_status']}:{days}")
    out["routing_trace"] = trace
    _log.info(
        "graph node=generate_itinerary status=%s day_blocks=%d",
        out["itinerary_status"],
        days,
    )
    return out


def build_planner_graph():
    """Compile planner graph: normalize → retrieve → places → weather → map → transport → routing → accommodation → itinerary."""
    g = StateGraph(PlannerState)

    g.add_node("normalize_profile", _normalize_profile)
    g.add_node("retrieve_context", _retrieve_context)
    g.add_node("enrich_places", _enrich_places)
    g.add_node("fetch_weather", _fetch_weather)
    g.add_node("build_map_points", _build_map_points)
    g.add_node("fetch_transport", _fetch_transport)
    g.add_node("multi_day_track", _multi_day_track)
    g.add_node("single_day_track", _single_day_track)
    g.add_node("merge", _merge_identity)
    g.add_node("accommodation", _with_accommodation)
    g.add_node("skip_accommodation", _skip_accommodation)
    g.add_node("generate_itinerary", _generate_itinerary)

    g.add_edge(START, "normalize_profile")
    g.add_edge("normalize_profile", "retrieve_context")
    g.add_edge("retrieve_context", "enrich_places")
    g.add_edge("enrich_places", "fetch_weather")
    g.add_edge("fetch_weather", "build_map_points")
    g.add_edge("build_map_points", "fetch_transport")
    g.add_conditional_edges(
        "fetch_transport",
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
    g.add_edge("accommodation", "generate_itinerary")
    g.add_edge("skip_accommodation", "generate_itinerary")
    g.add_edge("generate_itinerary", END)

    return g.compile()
