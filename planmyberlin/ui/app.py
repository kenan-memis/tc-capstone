"""PlanMyBerlin Streamlit UI — structured preferences + LangGraph orchestration."""

from __future__ import annotations

import html
import json
import os
import uuid
from pathlib import Path

import planmyberlin.env  # noqa: F401 — side-effect: load_dotenv + logging
import streamlit as st
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from streamlit_folium import st_folium

from planmyberlin.config.loader import (
    get_constants,
    get_dietary_options,
    get_interest_options,
    get_mobility_options,
    get_neighbourhood_options,
    get_settings,
)
from planmyberlin.graph.workflow import build_planner_graph
from planmyberlin.map import build_preview_map
from planmyberlin.map.interaction import itinerary_places_linked_to_map
from planmyberlin.models.trip_profile import TripProfile
from planmyberlin.observability import bind_run_context, get_logger


_ui_log = get_logger(__name__)


_BUILD_PHASE_ORDER = [
    "phase_preferences",
    "phase_places",
    "phase_weather_transport",
    "phase_itinerary",
    "phase_stays",
    "phase_prepare",
    "phase_finish",
]

_BUILD_PHASE_LABELS = {
    "phase_preferences": "Processing your preferences",
    "phase_places": "Finding places that match your trip",
    "phase_weather_transport": "Checking weather and local transport",
    "phase_itinerary": "Building your day-by-day itinerary",
    "phase_stays": "Adding stay suggestions",
    "phase_prepare": "Preparing map and trip details",
    "phase_finish": "Finalizing and displaying your plan",
}

_NODE_TO_PHASE = {
    "normalize_profile": "phase_preferences",
    "retrieve_context": "phase_places",
    "enrich_places": "phase_places",
    "fetch_weather": "phase_weather_transport",
    "fetch_transport": "phase_weather_transport",
    "multi_day_track": "phase_itinerary",
    "single_day_track": "phase_itinerary",
    "merge": "phase_itinerary",
    "generate_itinerary": "phase_itinerary",
    "accommodation": "phase_stays",
    "skip_accommodation": "phase_stays",
    "build_map_points": "phase_prepare",
}


def _default_index(options: tuple[str, ...], prefer: str) -> int:
    try:
        return options.index(prefer)
    except ValueError:
        return 0


def _weather_recommendation_text(bias: str) -> str:
    b = (bias or "").strip().lower()
    if b == "indoor":
        return "Based on expected conditions, indoor-focused activities are recommended."
    if b == "outdoor_or_mixed":
        return "Expected conditions support a balanced mix of outdoor and indoor activities."
    return "Weather is uncertain, so keeping a flexible indoor/outdoor mix is recommended."


def _weather_emoji(condition_main: str, bias: str) -> str:
    c = (condition_main or "").strip().lower()
    if "rain" in c or "drizzle" in c or "storm" in c:
        return "🌧️"
    if "snow" in c:
        return "❄️"
    if "cloud" in c:
        return "☁️"
    if "clear" in c or "sun" in c:
        return "☀️"
    if (bias or "").strip().lower() == "indoor":
        return "🏛️"
    return "🌤️"


def _activity_emoji(title: str, place_name: str, time_of_day: str) -> str:
    text = f"{title} {place_name}".lower()
    if "museum" in text or "gallery" in text:
        return "🏛️"
    if "cafe" in text or "coffee" in text:
        return "☕"
    if "dinner" in text or "lunch" in text or "breakfast" in text:
        return "🍽️"
    if "restaurant" in text or "food" in text or "eat" in text:
        return "🍴"
    if "park" in text or "garden" in text or "nature" in text:
        return "🌳"
    if "bar" in text or "beer" in text or "club" in text:
        return "🍸"
    return "📍"


def _time_of_day_emoji(time_of_day: str) -> str:
    tod = (time_of_day or "").strip().lower()
    if tod == "morning":
        return "🌅"
    if tod == "afternoon":
        return "🌇"
    if tod == "evening":
        return "🌙"
    return "🕒"


def _format_itinerary_markdown(itinerary: dict) -> str:
    title = str(itinerary.get("title", "Your plan")).strip()
    lines: list[str] = [f"## {title}", ""]
    for day in itinerary.get("days", []) if isinstance(itinerary.get("days"), list) else []:
        if not isinstance(day, dict):
            continue
        dn = day.get("day_number", "")
        theme = str(day.get("theme", "")).strip()
        lines.append(f"### Day {dn}: {theme}".strip())
        lines.append("")
        for act in day.get("activities", []) if isinstance(day.get("activities"), list) else []:
            if not isinstance(act, dict):
                continue
            tod = str(act.get("time_of_day", "")).strip()
            t = str(act.get("title", "")).strip()
            desc = str(act.get("description", "")).strip()
            pn = str(act.get("place_name", "")).strip()
            time_icon = _time_of_day_emoji(tod)
            event_icon = _activity_emoji(t, pn, tod)
            head = f"**{tod.title()} — {t}**" if tod else f"**{t}**"
            lines.append(f"- {time_icon} {head} {event_icon}")
            if pn:
                lines.append(f"  - Place: {pn}")
            if desc:
                lines.append(f"  - {desc}")
        lines.append("")
    notes = itinerary.get("practical_notes", [])
    if isinstance(notes, list) and notes:
        lines.append("**Practical notes**")
        for n in notes:
            if str(n).strip():
                lines.append(f"- {str(n).strip()}")
    return "\n".join(lines).strip()


def _stream_itinerary_markdown(itinerary: dict, *, model: str, temperature: float, placeholder) -> str:
    system = (
        "You are PlanMyBerlin. Turn the structured itinerary JSON into a friendly Markdown narrative.\n"
        "Do not invent new venues beyond those referenced in the JSON.\n"
        "Do not claim bookings or guaranteed availability.\n"
        "Use short sections per day with bullets."
    )
    human = "Itinerary JSON:\n" + json.dumps(itinerary, ensure_ascii=False, indent=2)
    llm = ChatOpenAI(model=model, temperature=temperature)
    text = ""
    for chunk in llm.stream([SystemMessage(content=system), HumanMessage(content=human)]):
        piece = getattr(chunk, "content", "") or ""
        if piece:
            text += piece
            placeholder.markdown(text)
    return text.strip()


def _map_highlight_option_list(linked: list[dict], map_points: list[dict]) -> list[str]:
    """Dropdown options: itinerary-linked names first, then other markers; always includes ``(All places)``."""
    ordered: list[str] = []
    seen: set[str] = set()
    for row in linked:
        n = str(row.get("name", "")).strip()
        if n and n not in seen:
            ordered.append(n)
            seen.add(n)
    for p in map_points:
        n = str(p.get("name", "")).strip()
        if n and n not in seen:
            ordered.append(n)
            seen.add(n)
    return ["(All places)"] + ordered


def _is_food_item(item: dict) -> bool:
    category = str(item.get("category", "")).strip().lower()
    return any(k in category for k in ("restaurant", "cafe", "bar", "food"))


def _merge_map_with_stays(
    map_points: list[dict],
    accommodation_items: list[dict],
) -> list[dict]:
    out = [dict(x) for x in map_points if isinstance(x, dict)]
    for stay in accommodation_items:
        if not isinstance(stay, dict):
            continue
        lat = stay.get("latitude")
        lng = stay.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue
        out.append(
            {
                "name": stay.get("name", ""),
                "category": "accommodation",
                "district": stay.get("district", ""),
                "summary": stay.get("reason", "") or stay.get("address", ""),
                "latitude": float(lat),
                "longitude": float(lng),
            }
        )
    return out


def _merge_display_items(retrieved_items: list[dict], enriched_items: list[dict]) -> list[dict]:
    """Merge retrieval + enrichment rows so partial enrichment does not hide categories."""
    out: list[dict] = []
    by_key: dict[str, int] = {}

    def _keys(item: dict) -> list[str]:
        keys: list[str] = []
        pid = str(item.get("place_id", "")).strip().lower()
        if pid:
            keys.append(f"pid:{pid}")
        nm = " ".join(str(item.get("name", "")).lower().split())
        if nm:
            keys.append(f"name:{nm}")
        return keys

    for row in retrieved_items:
        if not isinstance(row, dict):
            continue
        idx = len(out)
        out.append(dict(row))
        for k in _keys(row):
            by_key.setdefault(k, idx)

    for row in enriched_items:
        if not isinstance(row, dict):
            continue
        keys = _keys(row)
        match_idx = next((by_key[k] for k in keys if k in by_key), None)
        if match_idx is None:
            match_idx = len(out)
            out.append(dict(row))
        else:
            merged = dict(out[match_idx])
            merged.update(dict(row))
            out[match_idx] = merged
        for k in keys:
            by_key[k] = match_idx

    return out


def _walk_hint(distance_m: int | float | None) -> str:
    if not isinstance(distance_m, (int, float)):
        return "walking distance unavailable"
    d = int(distance_m)
    if d <= 250:
        return f"{d}m walk (very close)"
    if d <= 600:
        return f"{d}m walk (short walk)"
    return f"{d}m walk"


def _build_steps_markdown(completed_nodes: set[str], *, phase: str) -> str:
    completed_phases = {_NODE_TO_PHASE[n] for n in completed_nodes if n in _NODE_TO_PHASE}
    if phase in {"rendering", "ready"}:
        completed_phases.add("phase_prepare")
    if phase == "ready":
        completed_phases.add("phase_finish")
    lines: list[str] = []
    for p in _BUILD_PHASE_ORDER:
        label = _BUILD_PHASE_LABELS[p]
        if p in completed_phases:
            lines.append(f"✅ {label}")
        else:
            lines.append(f"⬜ {label}")
    # Force line-by-line rendering without markdown bullet semantics.
    return "  \n".join(lines)


def main() -> None:
    settings = get_settings()
    constants = get_constants()

    st.set_page_config(
        page_title=str(settings.get("page_title", "PlanMyBerlin")),
        page_icon=str(settings.get("page_icon", "🗺️")),
        layout=str(settings.get("layout", "wide")),
    )

    st.title(str(constants.get("hero_title", "PlanMyBerlin")))
    st.caption(str(constants.get("hero_subtitle", "")))
    st.info(str(constants.get("info_banner", "")))

    dietary_opts = tuple(get_dietary_options())
    mobility_opts = tuple(get_mobility_options())
    if not dietary_opts or not mobility_opts:
        st.error("Configuration error: dietary or mobility options missing from YAML.")
        return

    st.session_state.setdefault("plan_build_phase", "idle")
    st.session_state.setdefault("plan_build_nodes", [])

    top_left, top_right = st.columns([0.55, 0.45], gap="large")
    with top_left:
        st.subheader(str(constants.get("section_plan", "Your trip")))
        c1, c2 = st.columns(2)
        with c1:
            days = int(
                st.number_input(
                    str(constants.get("label_days", "Days")),
                    min_value=1,
                    max_value=14,
                    value=2,
                    step=1,
                )
            )
            party_size = int(
                st.number_input(
                    str(constants.get("label_party", "Party size")),
                    min_value=1,
                    max_value=20,
                    value=2,
                    step=1,
                )
            )
            default_include_acc = days >= 2
            include_accommodation = st.checkbox(
                str(constants.get("label_accommodation", "Include accommodation")),
                value=default_include_acc,
                help=str(constants.get("help_accommodation", "")),
            )

        with c2:
            budget_options = ("low", "moderate", "high")
            budget_tier = st.selectbox(
                str(constants.get("label_budget", "Budget")),
                options=budget_options,
                index=1,
            )
            pace_options = ("relaxed", "balanced", "packed")
            pace = st.selectbox(
                str(constants.get("label_pace", "Pace")),
                options=pace_options,
                index=1,
            )

        interest_options = list(get_interest_options())
        interest_tags = st.multiselect(
            str(constants.get("label_interests", "Interests")),
            options=interest_options,
            default=[],
            help=str(constants.get("help_interests", "")),
        )

        neighbourhood_options = list(get_neighbourhood_options())
        neighbourhoods = st.multiselect(
            str(constants.get("label_neighbourhoods", "Neighbourhoods")),
            options=neighbourhood_options,
            default=[],
            help=str(constants.get("help_neighbourhoods", "")),
        )

        d1, d2 = st.columns(2)
        with d1:
            dietary_choice = st.selectbox(
                str(constants.get("label_dietary", "Food & diet")),
                options=list(dietary_opts),
                index=_default_index(dietary_opts, "Doesn't matter / no preference"),
                help=str(constants.get("help_dietary", "")),
            )
        with d2:
            mobility_choice = st.selectbox(
                str(constants.get("label_mobility", "Walking & getting around")),
                options=list(mobility_opts),
                index=_default_index(mobility_opts, "No specific needs"),
                help=str(constants.get("help_mobility", "")),
            )

        extra_details = st.text_area(
            str(constants.get("label_notes", "Extra context")),
            value="",
            height=120,
            help=str(constants.get("help_notes", "")),
        )

        run_clicked = st.button(str(constants.get("button_run", "Run")), type="primary")

    with top_right:
        st.subheader("Plan builder list")
        latest_result = st.session_state.get("plan_result", {})
        latest_items = list(latest_result.get("enriched_items", [])) or list(latest_result.get("retrieved_items", []))
        latest_place_count = sum(1 for x in latest_items if not _is_food_item(x))
        latest_food_count = sum(1 for x in latest_items if _is_food_item(x))
        stat_1, stat_2, stat_3 = st.columns(3)
        with stat_1:
            st.metric("Places", latest_place_count)
        with stat_2:
            st.metric("Food", latest_food_count)
        with stat_3:
            st.metric("Stay", int(latest_result.get("accommodation_count", 0) or 0))
        status_panel = st.empty()
        steps_panel = st.empty()
        phase = str(st.session_state.get("plan_build_phase", "idle"))
        if phase == "building":
            status_panel.info("Building plan...")
        elif phase == "rendering":
            status_panel.info("Finalizing and displaying your plan...")
        elif phase == "ready":
            status_panel.success("Plan ready.")
        elif phase == "error":
            status_panel.error("Plan build failed.")
        else:
            status_panel.caption("Run the planner to see build progress and step logs.")
        completed_nodes = set(st.session_state.get("plan_build_nodes", []))
        if phase in {"building", "rendering", "ready", "error"}:
            steps_panel.markdown(_build_steps_markdown(completed_nodes, phase=phase))
        else:
            steps_panel.empty()

    if run_clicked:
        st.session_state["plan_build_phase"] = "building"
        st.session_state["plan_build_nodes"] = []
        profile = TripProfile(
            days=days,
            party_size=party_size,
            interest_tags=interest_tags,
            neighbourhoods=neighbourhoods,
            budget_tier=budget_tier,  # type: ignore[arg-type]
            pace=pace,  # type: ignore[arg-type]
            dietary_choice=dietary_choice,
            mobility_choice=mobility_choice,
            include_accommodation=include_accommodation,
            extra_details=extra_details,
        )
        graph = build_planner_graph()
        result: dict = {}
        run_id = str(uuid.uuid4())
        try:
            with bind_run_context(run_id):
                _ui_log.info("streamlit planner_stream_started days=%d", profile.days)
                status_panel.info("Building plan...")
                for event in graph.stream(
                    {"profile": profile.model_dump()},
                    {"metadata": {"run_id": run_id, "source": "streamlit"}},
                    stream_mode="updates",
                ):
                    if not isinstance(event, dict):
                        continue
                    for node_name, delta in event.items():
                        if str(node_name) not in st.session_state["plan_build_nodes"]:
                            st.session_state["plan_build_nodes"].append(str(node_name))
                        steps_panel.markdown(
                            _build_steps_markdown(set(st.session_state["plan_build_nodes"]), phase="building")
                        )
                        if isinstance(delta, dict):
                            result.update(delta)
                _ui_log.info(
                    "streamlit planner_stream_finished itinerary_status=%s",
                    result.get("itinerary_status"),
                )
            st.session_state["plan_build_phase"] = "rendering"
            status_panel.info("Preparing map and detail panels...")
        except Exception as exc:
            st.session_state["plan_build_phase"] = "error"
            _ui_log.warning("streamlit planner_stream_failed exc_type=%s", type(exc).__name__)
            st.error(f"Planning failed: {type(exc).__name__}")
            return
        st.session_state["plan_result"] = result
        st.session_state.pop("plan_narrative_md", None)
        st.session_state["map_highlight_pick"] = "(All places)"
        st.session_state["plan_map_version"] = str(uuid.uuid4())
        st.session_state["plan_build_phase"] = "ready"
        st.rerun()

    plan_result = st.session_state.get("plan_result")
    if not plan_result:
        return

    result = plan_result
    retrieved_items = list(result.get("retrieved_items", []))
    enriched_items = list(result.get("enriched_items", []))
    retrieval_notice = str(result.get("retrieval_notice", "")).strip()
    itinerary = result.get("itinerary", {})
    itinerary_status = str(result.get("itinerary_status", "unavailable"))
    itinerary_message = str(result.get("itinerary_message", "")).strip()
    transport_items = list(result.get("transport_items", []))
    transport_by_place = list(result.get("transport_by_place", []))
    accommodation_items = list(result.get("accommodation_items", []))
    map_points = list(result.get("map_points", []))
    map_status = str(result.get("map_status", "no_coordinates"))
    linked = itinerary_places_linked_to_map(itinerary, map_points) if isinstance(itinerary, dict) else []
    itinerary_only_points = linked if linked else []
    map_display_points = _merge_map_with_stays(itinerary_only_points, accommodation_items)
    linked_days = {row["name"]: row["days"] for row in linked}
    highlight_opts = _map_highlight_option_list(linked, map_display_points)

    bottom_left, bottom_right = st.columns([0.52, 0.48], gap="large")
    with bottom_left:
        st.subheader(str(constants.get("section_result", "Plan preview")))
        weather_summary = str(result.get("weather_summary", "")).strip()
        weather_bias = str(result.get("weather_bias", "unknown"))
        weather_condition_main = str(result.get("weather_condition_main", ""))
        if weather_summary:
            weather_icon = _weather_emoji(weather_condition_main, weather_bias)
            st.markdown(f"**{weather_icon} Expected weather on trip days:** {weather_summary}")
            st.caption(_weather_recommendation_text(weather_bias))
        if retrieval_notice:
            st.caption(retrieval_notice)
        if isinstance(itinerary, dict) and itinerary:
            st.markdown("**Your trip plan**")
            llm_cfg = settings.get("itinerary", {})
            narrative_stream = bool(llm_cfg.get("narrative_stream", False))
            if narrative_stream and os.getenv("OPENAI_API_KEY"):
                model = str(llm_cfg.get("model", "gpt-4o-mini"))
                temperature = float(llm_cfg.get("temperature", 0.4))
                cached_narrative = st.session_state.get("plan_narrative_md")
                if cached_narrative:
                    st.markdown(cached_narrative)
                else:
                    narrative_box = st.empty()
                    try:
                        text = _stream_itinerary_markdown(
                            itinerary, model=model, temperature=temperature, placeholder=narrative_box
                        )
                        if not text:
                            text = _format_itinerary_markdown(itinerary)
                        st.session_state.plan_narrative_md = text
                        narrative_box.markdown(text)
                    except Exception:
                        fallback_md = _format_itinerary_markdown(itinerary)
                        st.session_state.plan_narrative_md = fallback_md
                        narrative_box.markdown(fallback_md)
            else:
                st.markdown(_format_itinerary_markdown(itinerary))
            if itinerary_status != "ok" and itinerary_message:
                st.caption(itinerary_message)

    with bottom_right:
        st.subheader("Map & Trip Details")
        if map_display_points:
            st.caption(
                "Pick a place to emphasize on the map, or click a marker (tooltip = place name). "
                "Itinerary-linked stops are listed first."
            )
            st.caption("Marker colors: blue = places, yellow = food & drink, green = stays/hotels, red = selected marker.")
            pending_tip = st.session_state.pop("pending_map_highlight_pick", None)
            if pending_tip in highlight_opts:
                st.session_state["map_highlight_pick"] = pending_tip
            sel = st.selectbox("Focus marker", options=highlight_opts, key="map_highlight_pick")
            hl = None if sel == "(All places)" else sel
            pv = st.session_state.get("plan_map_version", "1")
            map_obj = build_preview_map(map_display_points, highlight_name=hl)
            map_out = st_folium(
                map_obj,
                width=None,
                height=420,
                returned_objects=["last_object_clicked_tooltip"],
                key=f"plan_map_{pv}",
            )
            tip = map_out.get("last_object_clicked_tooltip") if isinstance(map_out, dict) else None
            if tip and tip in highlight_opts and tip != sel:
                st.session_state["pending_map_highlight_pick"] = tip
                st.rerun()
        elif map_status != "ok":
            st.info("Map preview is unavailable because no coordinates were found for the current results.")
        else:
            st.info("Map currently shows only itinerary places; no itinerary locations had coordinates for this run.")

        tabs = st.tabs(
            [
                "🧭 Places to Explore",
                "☕ Food & Drink",
                "🚇 How to Get Around",
                "🏨 Stay Options",
                "🛠️ Developer Diagnostics",
                "🗂️ Raw Data",
                "📦 Structured itinerary (JSON)",
            ]
        )

        shown_items = _merge_display_items(retrieved_items, enriched_items)
        place_items = [x for x in shown_items if not _is_food_item(x)]
        food_items = [x for x in shown_items if _is_food_item(x)]
        with tabs[0]:
            if place_items:
                for item in place_items:
                    nm = str(item.get("name", "")).strip()
                    extra = ""
                    if nm in linked_days:
                        extra = (
                            f" · *Itinerary days: {', '.join(str(d) for d in linked_days[nm])}*"
                        )
                    st.markdown(
                        f"- **{item.get('name','')}** ({item.get('category','')}, {item.get('district','')})"
                        f" — {item.get('summary','')}{extra}"
                    )
            else:
                st.caption("No visit places found for this run.")

        with tabs[1]:
            if food_items:
                for item in food_items:
                    nm = str(item.get("name", "")).strip()
                    extra = ""
                    if nm in linked_days:
                        extra = (
                            f" · *Itinerary days: {', '.join(str(d) for d in linked_days[nm])}*"
                        )
                    st.markdown(
                        f"- **{item.get('name','')}** ({item.get('category','')}, {item.get('district','')})"
                        f" — {item.get('summary','')}{extra}"
                    )
            else:
                st.caption("No food & drink suggestions found for this run.")

        with tabs[2]:
            if transport_by_place:
                for row in transport_by_place:
                    if not isinstance(row, dict):
                        continue
                    place_name = str(row.get("place_name", "")).strip() or "Selected area"
                    options = row.get("options", [])
                    st.markdown(f"**For `{place_name}`**")
                    if isinstance(options, list) and options:
                        best = options[0] if isinstance(options[0], dict) else {}
                        if best:
                            st.markdown(
                                f"**Best option:** {best.get('name','Nearest stop')} — {_walk_hint(best.get('distance_m'))}"
                            )
                        with st.expander("See additional nearby options", expanded=False):
                            for idx, opt in enumerate(options):
                                if not isinstance(opt, dict):
                                    continue
                                if idx == 0:
                                    continue
                                st.markdown(
                                    f"- {opt.get('name','Unknown stop')} — {_walk_hint(opt.get('distance_m'))}"
                                )
                    else:
                        st.caption("No nearby stop details available for this place.")
                    st.divider()
            elif transport_items:
                for item in transport_items[:10]:
                    distance = item.get("distance_m")
                    distance_text = _walk_hint(distance if isinstance(distance, (int, float)) else None)
                    st.markdown(
                        f"- **{item.get('name','')}** — near {item.get('query','')} ({distance_text})"
                    )
            else:
                st.caption("No transport suggestions available for this run.")

        with tabs[3]:
            if accommodation_items:
                for item in accommodation_items[:5]:
                    name = html.escape(str(item.get("name", "")))
                    typ = html.escape(str(item.get("type", "")))
                    district = html.escape(str(item.get("district", "")))
                    reason = html.escape(str(item.get("reason", "")))
                    address = html.escape(str(item.get("address", "")))
                    rating = item.get("rating")
                    reviews = item.get("reviews")
                    rating_text = (
                        f"⭐ {rating:.1f} ({int(reviews)} reviews)"
                        if isinstance(rating, (int, float)) and isinstance(reviews, (int, float))
                        else "No verified review score available"
                    )
                    url = str(item.get("url", "")).strip()
                    photo_url = str(item.get("photo_url", "")).strip()
                    icon = (
                        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
                        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
                        '<polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>'
                        "</svg>"
                    )
                    link = (
                        f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer" '
                        f'title="Open in new tab" style="text-decoration:none;margin-left:6px;">{icon}</a>'
                    )
                    c_img, c_txt = st.columns([0.24, 0.76], gap="small")
                    with c_img:
                        if photo_url:
                            st.image(photo_url, use_container_width=True)
                    with c_txt:
                        st.markdown(
                            f"- **{name}** ({typ}, {district}) — {reason}  \n"
                            f"  - {rating_text}  \n"
                            f"  - {address} {link}",
                            unsafe_allow_html=True,
                        )
            else:
                st.caption("Accommodation suggestions are not enabled for this run.")

        with tabs[4]:
            st.caption("Temporary build-time diagnostics. Remove before final presentation.")
            st.markdown(
                "- Retrieval backend: "
                f"`{result.get('retrieval_backend', 'unknown')}`\n"
                "- Retrieval mode: "
                f"`{result.get('retrieval_mode', 'unknown')}`\n"
                "- Retrieved context items: "
                f"`{len(retrieved_items)}`\n"
                "- Places backend: "
                f"`{result.get('places_backend', 'unknown')}`\n"
                "- Place enrichment status: "
                f"`{result.get('places_status', 'unknown')}` / items `{len(enriched_items)}`\n"
                "- Transport backend: "
                f"`{result.get('transport_backend', 'unknown')}`\n"
                "- Transport status: "
                f"`{result.get('transport_status', 'unknown')}` / suggestions `{len(transport_items)}`\n"
                "- Accommodation backend: "
                f"`{result.get('accommodation_backend', 'unknown')}`\n"
                "- Accommodation status: "
                f"`{result.get('accommodation_status', 'unknown')}` / suggestions `{len(accommodation_items)}`\n"
                "- Itinerary status: "
                f"`{itinerary_status}`\n"
                "- Weather bias: "
                f"`{result.get('weather_bias', 'unknown')}`"
            )
            places_message = str(result.get("places_message", "")).strip()
            transport_message = str(result.get("transport_message", "")).strip()
            accommodation_message = str(result.get("accommodation_message", "")).strip()
            fallback_reason = str(result.get("retrieval_fallback_reason", "")).strip()
            if fallback_reason:
                st.caption(f"Retriever fallback: {fallback_reason}")
            if places_message:
                st.caption(f"Places message: {places_message}")
            if transport_message:
                st.caption(f"Transport message: {transport_message}")
            if accommodation_message:
                st.caption(f"Accommodation message: {accommodation_message}")
            if itinerary_message:
                st.caption(f"Itinerary message: {itinerary_message}")

            repo_root = Path(__file__).resolve().parents[2]
            graph_png = repo_root / "docs" / "graphs" / "planner_workflow.png"
            graph_mmd = repo_root / "docs" / "graphs" / "planner_workflow.mmd"
            st.markdown("**LangGraph workflow**")
            if graph_png.exists():
                st.image(str(graph_png), caption="Planner workflow graph")
            elif graph_mmd.exists():
                st.caption("PNG graph not found; showing Mermaid source.")
                with st.expander("Planner workflow Mermaid", expanded=False):
                    st.code(graph_mmd.read_text(encoding="utf-8"), language="mermaid")
                st.caption("Generate PNG with: `uv run planmyberlin-export-graphs`")
            else:
                st.caption("Graph export not found. Run: `uv run planmyberlin-export-graphs`")

        with tabs[5]:
            with st.expander("Raw result payload", expanded=False):
                st.json(result)

        with tabs[6]:
            st.caption("Developer-oriented structured itinerary. Remove before final presentation.")
            if isinstance(itinerary, dict) and itinerary:
                with st.expander("Structured itinerary JSON", expanded=False):
                    st.json(itinerary)
            else:
                st.caption("No itinerary JSON for this run.")




if __name__ == "__main__":
    main()
