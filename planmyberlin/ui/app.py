"""PlanMyBerlin Streamlit shell — env checks + stub LangGraph demo (Option B)."""

from __future__ import annotations

import os

import planmyberlin.env  # noqa: F401 — side-effect: load_dotenv
import streamlit as st

from planmyberlin.config.loader import get_constants, get_settings
from planmyberlin.graph.workflow import build_planner_graph


def main() -> None:
    settings = get_settings()
    constants = get_constants()

    st.set_page_config(
        page_title=str(settings.get("page_title", "PlanMyBerlin")),
        page_icon=str(settings.get("page_icon", "🗺️")),
        layout=str(settings.get("layout", "wide")),
    )

    st.title(str(constants.get("hero_title", "PlanMyBerlin")))
    st.markdown(str(constants.get("hero_subtitle", "")))
    st.info(str(constants.get("stub_banner", "")))

    st.subheader("API keys (same names as Sprint 2 / Cloud Run)")
    openai_ok = bool(os.getenv("OPENAI_API_KEY"))
    gemini_ok = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))

    if openai_ok:
        st.success("`OPENAI_API_KEY` is set.")
    else:
        st.error("Missing `OPENAI_API_KEY`. Set it in `.env` or the environment.")

    if gemini_ok:
        st.success("`GEMINI_API_KEY` or `GOOGLE_API_KEY` is set.")
    else:
        st.warning("Gemini optional: set `GEMINI_API_KEY` or `GOOGLE_API_KEY` if you use Gemini.")

    st.divider()
    st.subheader("LangGraph stub (conditional routing)")
    needs_hotel = st.checkbox("Needs accommodation for this demo run", value=False)
    days = st.number_input("Trip length (days)", min_value=1, max_value=14, value=2, step=1)

    if st.button("Run stub graph"):
        graph = build_planner_graph()
        result = graph.invoke({"needs_accommodation": needs_hotel, "days": int(days)})
        st.json(result)


if __name__ == "__main__":
    main()
