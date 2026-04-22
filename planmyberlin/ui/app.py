"""PlanMyBerlin Streamlit UI — structured preferences + LangGraph orchestration."""

from __future__ import annotations

import html
import json
import os
import uuid

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


def _default_index(options: tuple[str, ...], prefer: str) -> int:
    try:
        return options.index(prefer)
    except ValueError:
        return 0


def _step_label(node_name: str) -> str:
    labels = {
        "normalize_profile": "Normalizing your trip preferences",
        "retrieve_context": "Retrieving matching context",
        "enrich_places": "Enriching places with live details",
        "fetch_weather": "Checking current weather",
        "build_map_points": "Preparing map markers",
        "fetch_transport": "Checking transport options",
        "multi_day_track": "Applying multi-day planning route",
        "single_day_track": "Applying single-day planning route",
        "merge": "Merging planning state",
        "accommodation": "Adding accommodation suggestions",
        "skip_accommodation": "Skipping accommodation suggestions",
        "generate_itinerary": "Drafting your day-by-day plan",
    }
    return labels.get(node_name, f"Running {node_name}")


def _weather_recommendation_text(bias: str) -> str:
    b = (bias or "").strip().lower()
    if b == "indoor":
        return "Based on expected conditions, indoor-focused activities are recommended."
    if b == "outdoor_or_mixed":
        return "Expected conditions support a balanced mix of outdoor and indoor activities."
    return "Weather is uncertain, so keeping a flexible indoor/outdoor mix is recommended."


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
            head = f"**{tod.title()} — {t}**" if tod else f"**{t}**"
            lines.append(f"- {head}")
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

    st.subheader(str(constants.get("section_plan", "Your trip")))

    dietary_opts = tuple(get_dietary_options())
    mobility_opts = tuple(get_mobility_options())
    if not dietary_opts or not mobility_opts:
        st.error("Configuration error: dietary or mobility options missing from YAML.")
        return

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

    if run_clicked:
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
        with st.status("Building your plan...", expanded=True) as status:
            try:
                with bind_run_context(run_id):
                    _ui_log.info("streamlit planner_stream_started days=%d", profile.days)
                    for event in graph.stream(
                        {"profile": profile.model_dump()},
                        {"metadata": {"run_id": run_id, "source": "streamlit"}},
                        stream_mode="updates",
                    ):
                        if not isinstance(event, dict):
                            continue
                        for node_name, delta in event.items():
                            status.write(f"• {_step_label(str(node_name))}")
                            if isinstance(delta, dict):
                                result.update(delta)
                    _ui_log.info(
                        "streamlit planner_stream_finished itinerary_status=%s",
                        result.get("itinerary_status"),
                    )
                status.update(label="Plan built", state="complete")
            except Exception as exc:
                status.update(label="Plan build failed", state="error")
                _ui_log.warning("streamlit planner_stream_failed exc_type=%s", type(exc).__name__)
                st.error(f"Planning failed: {type(exc).__name__}")
                return
        st.session_state["plan_result"] = result
        st.session_state.pop("plan_narrative_md", None)
        st.session_state["map_highlight_pick"] = "(All places)"
        st.session_state["plan_map_version"] = str(uuid.uuid4())

    plan_result = st.session_state.get("plan_result")
    if not plan_result:
        return

    result = plan_result
    st.subheader(str(constants.get("section_result", "Plan preview")))

    retrieved_items = list(result.get("retrieved_items", []))
    enriched_items = list(result.get("enriched_items", []))

    weather_summary = str(result.get("weather_summary", "")).strip()
    weather_bias = str(result.get("weather_bias", "unknown"))
    if weather_summary:
        st.markdown(f"**Expected weather on trip days:** {weather_summary}")
        st.caption(_weather_recommendation_text(weather_bias))

    itinerary = result.get("itinerary", {})
    itinerary_status = str(result.get("itinerary_status", "unavailable"))
    itinerary_message = str(result.get("itinerary_message", "")).strip()
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

    transport_items = list(result.get("transport_items", []))
    accommodation_items = list(result.get("accommodation_items", []))

    map_points = list(result.get("map_points", []))
    map_status = str(result.get("map_status", "no_coordinates"))
    linked = itinerary_places_linked_to_map(itinerary, map_points) if isinstance(itinerary, dict) else []
    linked_days = {row["name"]: row["days"] for row in linked}
    highlight_opts = _map_highlight_option_list(linked, map_points)

    if map_points:
        st.markdown("##### Map")
        st.caption(
            "Pick a place to emphasize on the map, or click a marker (tooltip = place name). "
            "Itinerary-linked stops are listed first."
        )
        pending_tip = st.session_state.pop("pending_map_highlight_pick", None)
        if pending_tip in highlight_opts:
            st.session_state["map_highlight_pick"] = pending_tip
        sel = st.selectbox("Focus marker", options=highlight_opts, key="map_highlight_pick")
        hl = None if sel == "(All places)" else sel
        pv = st.session_state.get("plan_map_version", "1")
        map_obj = build_preview_map(map_points, highlight_name=hl)
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

    st.caption("Use the tabs below for places, transport, and stay details. The main itinerary stays above the map.")
    tabs = st.tabs(
        [
            "Places to Explore",
            "How to Get Around",
            "Stay Options",
            "Developer Diagnostics",
            "Raw Data",
            "Structured itinerary (JSON)",
        ]
    )

    shown_items = enriched_items if enriched_items else retrieved_items
    with tabs[0]:
        if shown_items:
            for item in shown_items:
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
            st.caption("No places found for this run.")

    with tabs[1]:
        if transport_items:
            for item in transport_items[:10]:
                distance = item.get("distance_m")
                distance_text = f", ~{int(distance)}m away" if isinstance(distance, (int, float)) else ""
                st.markdown(
                    f"- **{item.get('name','')}** ({item.get('type','')})"
                    f" — near: {item.get('query','')}{distance_text}"
                )
        else:
            st.caption("No transport suggestions available for this run.")

    with tabs[2]:
        if accommodation_items:
            for item in accommodation_items[:5]:
                name = html.escape(str(item.get("name", "")))
                typ = html.escape(str(item.get("type", "")))
                district = html.escape(str(item.get("district", "")))
                reason = html.escape(str(item.get("reason", "")))
                url = str(item.get("url", "")).strip()
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
                st.markdown(
                    f"- **{name}** ({typ}, {district}) — {reason} {link}",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Accommodation suggestions are not enabled for this run.")

    with tabs[3]:
        st.caption("Temporary build-time diagnostics. Remove before final presentation.")
        st.markdown(
            "- Retrieval backend: "
            f"`{result.get('retrieval_backend', 'unknown')}`\n"
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
            f"`{weather_bias}`"
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

    with tabs[4]:
        st.json(result)

    with tabs[5]:
        st.caption("Developer-oriented structured itinerary. Remove before final presentation.")
        if isinstance(itinerary, dict) and itinerary:
            st.json(itinerary)
        else:
            st.caption("No itinerary JSON for this run.")




if __name__ == "__main__":
    main()
