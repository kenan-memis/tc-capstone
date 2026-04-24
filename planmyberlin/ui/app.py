"""PlanMyBerlin Streamlit UI — structured preferences + LangGraph orchestration."""

from __future__ import annotations

import base64
import html
import json
import os
import uuid
from datetime import date, timedelta
from functools import lru_cache
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

_TIME_ICON_PATHS: dict[str, Path] = {
    "morning": Path(
        "/Users/kenan/.cursor/projects/Users-kenan-Workshop-turing-college-projects-capstone/assets/morning-6bb8cac5-de7c-4030-b367-be3ec132a85b.png"
    ),
    "afternoon": Path(
        "/Users/kenan/.cursor/projects/Users-kenan-Workshop-turing-college-projects-capstone/assets/afternoon-fc911002-3c3d-410b-94ff-26e65fa5292e.png"
    ),
    "evening": Path(
        "/Users/kenan/.cursor/projects/Users-kenan-Workshop-turing-college-projects-capstone/assets/evening-3a9f9fd8-6d10-4eeb-86de-4c8678a91b3c.png"
    ),
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


def _weather_support_text(bias: str) -> str:
    b = (bias or "").strip().lower()
    if b == "indoor":
        return "indoor-focused activities."
    if b == "outdoor_or_mixed":
        return "a balanced mix of outdoor and indoor activities."
    return "a flexible indoor/outdoor mix."


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
        return "🌄"
    if tod == "afternoon":
        return "🌞"
    if tod == "evening":
        return "🌆"
    return "🕒"


@lru_cache(maxsize=16)
def _icon_data_uri(path: str) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    payload = p.read_bytes()
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _time_of_day_icon_html(time_of_day: str) -> str:
    tod = (time_of_day or "").strip().lower()
    icon_path = _TIME_ICON_PATHS.get(tod)
    if icon_path is None:
        return _time_of_day_emoji(time_of_day)
    uri = _icon_data_uri(str(icon_path))
    if not uri:
        return _time_of_day_emoji(time_of_day)
    return (
        f'<img src="{uri}" alt="{html.escape(tod)}" '
        'style="width:18px;height:18px;vertical-align:-3px;margin-right:6px;border-radius:3px;" />'
    )


def _format_itinerary_markdown(itinerary: dict) -> str:
    days = itinerary.get("days", [])
    day_list = days if isinstance(days, list) else []
    single_day = len(day_list) == 1
    lines: list[str] = []
    for day in day_list:
        if not isinstance(day, dict):
            continue
        dn = day.get("day_number", "")
        theme = html.escape(str(day.get("theme", "")).strip())
        if single_day:
            if theme:
                lines.append(f"### {theme}")
        else:
            lines.append(f"### Day {dn}: {theme}".strip())
        lines.append("")
        for act in day.get("activities", []) if isinstance(day.get("activities"), list) else []:
            if not isinstance(act, dict):
                continue
            tod = str(act.get("time_of_day", "")).strip()
            t = html.escape(str(act.get("title", "")).strip())
            desc = html.escape(str(act.get("description", "")).strip())
            pn = html.escape(str(act.get("place_name", "")).strip())
            time_icon = _time_of_day_icon_html(tod)
            event_icon = _activity_emoji(t, pn, tod)
            tod_label = html.escape(tod.title())
            head = f"**{tod_label} — {t}**" if tod else f"**{t}**"
            lines.append(f"- {time_icon} {head} {event_icon}")
            if pn:
                lines.append(f"  - Place: {pn}")
            if desc:
                lines.append(f"  - {desc}")
        lines.append("")
    return "\n".join(lines).strip()


def _clean_weather_summary(summary: str) -> str:
    s = (summary or "").strip()
    prefix = "Current weather in Berlin:"
    if s.lower().startswith(prefix.lower()):
        return s[len(prefix) :].strip()
    forecast_prefix = "Forecast for "
    if s.lower().startswith(forecast_prefix.lower()) and ":" in s:
        return s.split(":", 1)[1].strip()
    return s


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

    dietary_opts = tuple(get_dietary_options())
    mobility_opts = tuple(get_mobility_options())
    if not dietary_opts or not mobility_opts:
        st.error("Configuration error: dietary or mobility options missing from YAML.")
        return

    st.session_state.setdefault("plan_build_phase", "idle")
    st.session_state.setdefault("plan_build_nodes", [])
    st.session_state.setdefault("plan_build_summary", None)

    banner_left, _banner_right = st.columns([0.55, 0.45], gap="large")
    with banner_left:
        st.info(str(constants.get("info_banner", "")))

    top_left, top_right = st.columns([0.55, 0.45], gap="large")
    with top_left:
        default_start = st.session_state.get("plan_start_date", date.today())
        if not isinstance(default_start, date):
            default_start = date.today()
        default_end = st.session_state.get("plan_end_date")
        if not isinstance(default_end, date):
            default_end = default_start + timedelta(days=1)
        if default_end < default_start:
            default_end = default_start
        preview_days = (default_end - default_start).days + 1
        st.subheader(f"{str(constants.get('section_plan', 'Your trip'))} - {preview_days} day(s)")

        r1c1, r1c2, r1c3 = st.columns(3)
        with r1c1:
            start_date = st.date_input(
                str(constants.get("label_start_date", "Trip start date")),
                value=default_start,
                min_value=date.today(),
                help=str(constants.get("help_start_date", "")),
            )
            st.session_state["plan_start_date"] = start_date
        with r1c2:
            end_value = default_end if default_end >= start_date else start_date
            end_date = st.date_input(
                str(constants.get("label_end_date", "Trip end date")),
                value=end_value,
                min_value=start_date,
                max_value=start_date + timedelta(days=13),
                help=str(constants.get("help_end_date", "")),
            )
            st.session_state["plan_end_date"] = end_date
        with r1c3:
            party_size = int(
                st.number_input(
                    str(constants.get("label_party", "Party size")),
                    min_value=1,
                    max_value=20,
                    value=2,
                    step=1,
                )
            )
        days = (end_date - start_date).days + 1

        budget_options = ("low", "moderate", "high")
        pace_options = ("relaxed", "balanced", "packed")
        r2c1, r2c2, r2c3 = st.columns(3)
        with r2c1:
            pace = st.selectbox(
                str(constants.get("label_pace", "Pace")),
                options=pace_options,
                index=1,
            )
        with r2c2:
            budget_tier = st.selectbox(
                str(constants.get("label_budget", "Budget")),
                options=budget_options,
                index=1,
            )
        with r2c3:
            dietary_choice = st.selectbox(
                str(constants.get("label_dietary", "Food & diet")),
                options=list(dietary_opts),
                index=_default_index(dietary_opts, "Doesn't matter / no preference"),
                help=str(constants.get("help_dietary", "")),
            )

        interest_options = list(get_interest_options())
        neighbourhood_options = list(get_neighbourhood_options())
        r3c1, r3c2, r3c3 = st.columns(3)
        with r3c1:
            mobility_choice = st.selectbox(
                str(constants.get("label_mobility", "Walking & getting around")),
                options=list(mobility_opts),
                index=_default_index(mobility_opts, "No specific needs"),
                help=str(constants.get("help_mobility", "")),
            )
        with r3c2:
            interest_tags = st.multiselect(
                str(constants.get("label_interests", "Interests")),
                options=interest_options,
                default=[],
                help=str(constants.get("help_interests", "")),
            )
        with r3c3:
            neighbourhoods = st.multiselect(
                str(constants.get("label_neighbourhoods", "Neighbourhoods")),
                options=neighbourhood_options,
                default=[],
                help=str(constants.get("help_neighbourhoods", "")),
            )

        extra_details = st.text_area(
            str(constants.get("label_notes", "Extra context")),
            value="",
            height=120,
            help=str(constants.get("help_notes", "")),
        )

        default_include_acc = days >= 2
        include_accommodation = st.checkbox(
            str(constants.get("label_accommodation", "Include accommodation")),
            value=default_include_acc,
            help=str(constants.get("help_accommodation", "")),
        )

        run_clicked = st.button(str(constants.get("button_run", "Run")), type="primary")

    with top_right:
        st.subheader("Plan builder list")
        status_panel = st.empty()
        steps_panel = st.empty()
        summary_panel = st.empty()
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
            summary_text = st.session_state.get("plan_build_summary")
            if isinstance(summary_text, str) and summary_text.strip():
                summary_panel.caption(summary_text)
            else:
                summary_panel.empty()
        else:
            steps_panel.empty()
            summary_panel.empty()

    if run_clicked:
        st.session_state["plan_build_phase"] = "building"
        st.session_state["plan_build_nodes"] = []
        interests_short = ", ".join(interest_tags[:2]) + (f" +{len(interest_tags) - 2} more" if len(interest_tags) > 2 else "")
        areas_short = ", ".join(neighbourhoods[:2]) + (f" +{len(neighbourhoods) - 2} more" if len(neighbourhoods) > 2 else "")
        summary_lines = [
            f"**Trip summary:** {days} day(s), {party_size} traveler(s), {pace} pace, {budget_tier} budget.",
            f"**Food/mobility:** {dietary_choice}; {mobility_choice}.",
            f"**Stay ideas:** {'on' if include_accommodation else 'off'}.",
        ]
        if interests_short:
            summary_lines.append(f"**Interests:** {interests_short}.")
        if areas_short:
            summary_lines.append(f"**Areas:** {areas_short}.")
        st.session_state["plan_build_summary"] = "  \n".join(summary_lines)
        profile = TripProfile(
            days=days,
            start_date=start_date,
            end_date=end_date,
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
    profile_data = result.get("profile", {}) if isinstance(result.get("profile"), dict) else {}
    trip_start = str(profile_data.get("start_date", "")).strip()
    trip_end = str(profile_data.get("end_date", "")).strip()
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
        st.markdown("## Plan Preview")
        if trip_start and trip_end:
            st.caption(f"Trip dates: {trip_start} to {trip_end}")
        weather_summary = str(result.get("weather_summary", "")).strip()
        weather_bias = str(result.get("weather_bias", "unknown"))
        weather_condition_main = str(result.get("weather_condition_main", ""))
        practical_notes = itinerary.get("practical_notes", []) if isinstance(itinerary, dict) else []
        preview_tabs = st.tabs(["🗓️ Berlin Itinerary", "🌤️ Weather", "📝 Practical Notes"])

        with preview_tabs[0]:
            if isinstance(itinerary, dict) and itinerary:
                llm_cfg = settings.get("itinerary", {})
                narrative_stream = bool(llm_cfg.get("narrative_stream", False))
                if narrative_stream and os.getenv("OPENAI_API_KEY"):
                    model = str(llm_cfg.get("model", "gpt-4o-mini"))
                    temperature = float(llm_cfg.get("temperature", 0.4))
                    cached_narrative = st.session_state.get("plan_narrative_md")
                    if cached_narrative:
                        st.markdown(cached_narrative, unsafe_allow_html="<img" in str(cached_narrative))
                    else:
                        narrative_box = st.empty()
                        try:
                            text = _stream_itinerary_markdown(
                                itinerary, model=model, temperature=temperature, placeholder=narrative_box
                            )
                            if not text:
                                text = _format_itinerary_markdown(itinerary)
                                narrative_box.markdown(text, unsafe_allow_html=True)
                            else:
                                narrative_box.markdown(text)
                            st.session_state.plan_narrative_md = text
                        except Exception:
                            fallback_md = _format_itinerary_markdown(itinerary)
                            st.session_state.plan_narrative_md = fallback_md
                            narrative_box.markdown(fallback_md, unsafe_allow_html=True)
                else:
                    st.markdown(_format_itinerary_markdown(itinerary), unsafe_allow_html=True)
                if itinerary_status != "ok" and itinerary_message and (
                    itinerary_message.strip().lower()
                    != "venue names were aligned with retrieved candidates."
                ):
                    st.caption(itinerary_message)
            else:
                st.caption("No itinerary was generated for this run.")

        with preview_tabs[1]:
            clean_weather = _clean_weather_summary(weather_summary)
            if weather_summary:
                weather_icon = _weather_emoji(weather_condition_main, weather_bias)
                st.markdown(f"- **Expected weather on trip days:** {weather_icon} {clean_weather}")
                st.markdown(f"- **Expected conditions support:** {_weather_support_text(weather_bias)}")
            else:
                st.markdown("- **Expected weather on trip days:** unavailable for this run.")
                st.markdown("- **Expected conditions support:** a flexible indoor/outdoor mix.")

        with preview_tabs[2]:
            if isinstance(practical_notes, list) and practical_notes:
                for note in practical_notes:
                    text = str(note).strip()
                    if text:
                        st.markdown(f"- {text}")
            else:
                st.caption("No practical notes were generated for this run.")

    with bottom_right:
        st.subheader("Map & Trip Details")
        if map_display_points:
            pending_tip = st.session_state.pop("pending_map_highlight_pick", None)
            sel = st.session_state.get("map_highlight_pick", "(All places)")
            if pending_tip in highlight_opts:
                sel = pending_tip
                st.session_state["map_highlight_pick"] = sel
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
            st.caption("Marker colors: blue = places, yellow = food & drink, green = stays/hotels, red = selected marker.")
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
