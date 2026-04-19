"""PlanMyBerlin Streamlit UI — structured preferences + LangGraph orchestration."""

from __future__ import annotations

import planmyberlin.env  # noqa: F401 — side-effect: load_dotenv
import streamlit as st

from planmyberlin.config.loader import (
    get_constants,
    get_dietary_options,
    get_interest_options,
    get_mobility_options,
    get_neighbourhood_options,
    get_settings,
)
from planmyberlin.graph.workflow import build_planner_graph
from planmyberlin.models.trip_profile import TripProfile


def _default_index(options: tuple[str, ...], prefer: str) -> int:
    try:
        return options.index(prefer)
    except ValueError:
        return 0


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
        result = graph.invoke({"profile": profile.model_dump()})
        st.subheader(str(constants.get("section_result", "Plan preview")))
        st.json(result)


if __name__ == "__main__":
    main()
