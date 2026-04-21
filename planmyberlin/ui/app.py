"""PlanMyBerlin Streamlit UI — structured preferences + LangGraph orchestration."""

from __future__ import annotations

import planmyberlin.env  # noqa: F401 — side-effect: load_dotenv
import streamlit as st
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
from planmyberlin.models.trip_profile import TripProfile



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
        "multi_day_track": "Applying multi-day planning route",
        "single_day_track": "Applying single-day planning route",
        "merge": "Merging planning state",
        "accommodation": "Adding accommodation suggestions",
        "skip_accommodation": "Skipping accommodation suggestions",
    }
    return labels.get(node_name, f"Running {node_name}")


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

    if st.button(str(constants.get("button_run", "Run")), type="primary"):
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
        with st.status("Building your plan...", expanded=True) as status:
            try:
                for event in graph.stream({"profile": profile.model_dump()}, stream_mode="updates"):
                    if not isinstance(event, dict):
                        continue
                    for node_name, delta in event.items():
                        status.write(f"• {_step_label(str(node_name))}")
                        if isinstance(delta, dict):
                            result.update(delta)
                status.update(label="Plan built", state="complete")
            except Exception as exc:
                status.update(label="Plan build failed", state="error")
                st.error(f"Planning failed: {type(exc).__name__}")
                return
        st.subheader(str(constants.get("section_result", "Plan preview")))

        backend = str(result.get("retrieval_backend", "seed"))
        retrieved_items = list(result.get("retrieved_items", []))
        st.caption(f"Retrieved context items: {len(retrieved_items)} (backend: {backend})")

        fallback_reason = str(result.get("retrieval_fallback_reason", "")).strip()
        if fallback_reason:
            st.warning(f"Retriever fallback: {fallback_reason}")

        places_status = str(result.get("places_status", "unavailable"))
        places_backend = str(result.get("places_backend", "serpapi"))
        enriched_items = list(result.get("enriched_items", []))
        st.markdown(
            f"**{constants.get('section_places', 'Place enrichment')}:** "
            f"{places_status} ({places_backend}), {len(enriched_items)} items"
        )
        places_message = str(result.get("places_message", "")).strip()
        if places_message and places_status != "ok":
            st.caption(places_message)

        weather_summary = str(result.get("weather_summary", "")).strip()
        if weather_summary:
            st.markdown(f"**{constants.get('section_weather', 'Weather signal')}:** {weather_summary}")
            st.caption(
                f"{constants.get('label_weather_bias', 'Planning bias')}: "
                f"{result.get('weather_bias', 'unknown')}"
            )

        map_points = list(result.get("map_points", []))
        map_status = str(result.get("map_status", "no_coordinates"))
        st.markdown(f"**Map markers:** {len(map_points)}")
        if map_points:
            map_obj = build_preview_map(map_points)
            st_folium(map_obj, width=None, height=420, returned_objects=[])
        elif map_status != "ok":
            st.info("Map preview is unavailable because no coordinates were found for the current results.")

        shown_items = enriched_items if enriched_items else retrieved_items
        if shown_items:
            with st.expander("Retrieved places and restaurants", expanded=True):
                for item in shown_items:
                    coord = ""
                    lat = item.get("latitude")
                    lng = item.get("longitude")
                    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
                        coord = f" [lat={lat:.4f}, lng={lng:.4f}]"
                    st.markdown(
                        f"- **{item.get('name','')}** ({item.get('category','')}, {item.get('district','')})"
                        f" — {item.get('summary','')}{coord}"
                    )
        st.json(result)


if __name__ == "__main__":
    main()
