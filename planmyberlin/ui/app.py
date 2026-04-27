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
from planmyberlin.profiles import AppUser, UserProfileUpsert, build_user_profile_repository


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

_TRANSPORT_ICON_PATHS: dict[str, Path] = {
    "s_bahn": Path(
        "/Users/kenan/.cursor/projects/Users-kenan-Workshop-turing-college-projects-capstone/assets/Screenshot_2026-04-24_at_16.17.54-04e76c10-a25f-4288-a938-6ae8b3ca3111.png"
    ),
    "bus": Path(
        "/Users/kenan/.cursor/projects/Users-kenan-Workshop-turing-college-projects-capstone/assets/Screenshot_2026-04-24_at_16.19.01-06db2610-0c2a-4aa3-8c80-d2fda362eb18.png"
    ),
    "tram": Path(
        "/Users/kenan/.cursor/projects/Users-kenan-Workshop-turing-college-projects-capstone/assets/Screenshot_2026-04-24_at_16.18.18-850fb6bb-18db-4b73-8f4c-951606b03785.png"
    ),
    "u_bahn": Path(
        "/Users/kenan/.cursor/projects/Users-kenan-Workshop-turing-college-projects-capstone/assets/Screenshot_2026-04-24_at_16.18.02-58c6c510-339f-4933-83e7-9c02752ef81b.png"
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


def _format_display_date(raw: str) -> str:
    text = (raw or "").strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        y, m, d = text.split("-")
        return f"{d}-{m}-{y}"
    return text


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


def _transport_mode_icons_html(modes: list[str]) -> str:
    if not isinstance(modes, list) or not modes:
        return ""
    chunks: list[str] = []
    for mode in modes:
        p = _TRANSPORT_ICON_PATHS.get(str(mode).strip().lower())
        if not p:
            continue
        uri = _icon_data_uri(str(p))
        if not uri:
            continue
        chunks.append(
            f'<img src="{uri}" alt="{html.escape(str(mode))}" '
            'style="width:16px;height:16px;vertical-align:-2px;margin-right:4px;border-radius:2px;" />'
        )
    if not chunks:
        return ""
    return "".join(chunks) + " "


def _is_user_facing_practical_note(note: str) -> bool:
    n = (note or "").strip().lower()
    if not n:
        return False
    blocked_markers = (
        "allowed list",
        "retrieved candidate list",
        "venue links were removed",
        "adjusted place names",
    )
    return not any(marker in n for marker in blocked_markers)


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


def _plan_summary_from_result(result: dict[str, object]) -> str:
    profile = result.get("profile", {}) if isinstance(result, dict) else {}
    p = profile if isinstance(profile, dict) else {}
    start = _format_display_date(str(p.get("start_date", "")).strip())
    end = _format_display_date(str(p.get("end_date", "")).strip())
    days = int(p.get("days", 0) or 0)
    party = int(p.get("party_size", 0) or 0)
    pace = str(p.get("pace", "")).strip()
    budget = str(p.get("budget_tier", "")).strip()
    dietary = str(p.get("dietary_choice", "")).strip()
    mobility = str(p.get("mobility_choice", "")).strip()
    include_acc = bool(p.get("include_accommodation", False))
    interests = p.get("interest_tags", [])
    areas = p.get("neighbourhoods", [])
    interests_list = [str(x).strip() for x in interests if str(x).strip()] if isinstance(interests, list) else []
    areas_list = [str(x).strip() for x in areas if str(x).strip()] if isinstance(areas, list) else []
    interests_short = ", ".join(interests_list[:2]) + (f" +{len(interests_list) - 2} more" if len(interests_list) > 2 else "")
    areas_short = ", ".join(areas_list[:2]) + (f" +{len(areas_list) - 2} more" if len(areas_list) > 2 else "")
    lines = []
    if start and end:
        lines.append(f"**Dates:** {start} to {end}.")
    if days:
        lines.append(f"**Trip summary:** {days} day(s), {party} traveler(s), {pace} pace, {budget} budget.")
    if dietary or mobility:
        lines.append(f"**Food/mobility:** {dietary}; {mobility}.")
    lines.append(f"**Accommodation:** {'requested' if include_acc else 'not requested'}.")
    if interests_short:
        lines.append(f"**Interests:** {interests_short}.")
    if areas_short:
        lines.append(f"**Areas:** {areas_short}.")
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
    st.session_state.setdefault("auth_user_id", None)
    st.session_state.setdefault("auth_username", "")
    st.session_state.setdefault("auth_onboarding_completed", False)
    st.session_state.setdefault("auth_session_token", "")
    st.session_state.setdefault("form_start_date", date.today())
    st.session_state.setdefault("form_end_date", date.today() + timedelta(days=1))
    st.session_state.setdefault("form_party_size", 2)
    st.session_state.setdefault("form_budget_tier", "moderate")
    st.session_state.setdefault("form_pace", "balanced")
    st.session_state.setdefault("form_dietary_choice", "Doesn't matter / no preference")
    st.session_state.setdefault("form_mobility_choice", "No specific needs")
    st.session_state.setdefault("form_interest_tags", [])
    st.session_state.setdefault("form_neighbourhoods", [])
    st.session_state.setdefault("form_extra_details", "")
    st.session_state.setdefault("form_include_accommodation", True)
    st.session_state.setdefault("loaded_latest_plan_user_id", None)

    profile_repo = None
    auth_user: AppUser | None = None
    try:
        profile_repo = build_user_profile_repository()
        qs_token = str(st.query_params.get("auth_token", "")).strip()
        if qs_token and not st.session_state.get("auth_user_id"):
            user_by_session = profile_repo.get_user_by_session(token=qs_token)
            if user_by_session is not None:
                st.session_state["auth_user_id"] = user_by_session.id
                st.session_state["auth_username"] = user_by_session.username
                st.session_state["auth_onboarding_completed"] = bool(user_by_session.onboarding_completed)
                st.session_state["auth_session_token"] = qs_token
        current_user_id = st.session_state.get("auth_user_id")
        if isinstance(current_user_id, str):
            auth_user = profile_repo.get_user(current_user_id)
    except Exception:
        profile_repo = None
        auth_user = None

    if profile_repo is None:
        st.error("User storage is unavailable right now.")
        return

    if auth_user is None:
        st.subheader("Sign in")
        tab_login, tab_signup = st.tabs(["Login", "Create account"])
        with tab_login:
            login_username = st.text_input("Username", key="login_username")
            login_password = st.text_input("Password", type="password", key="login_password")
            if st.button("Login"):
                user = profile_repo.authenticate_user(username=login_username, password=login_password)
                if user is None:
                    st.error("Invalid username or password.")
                else:
                    session_token = profile_repo.create_session(user_id=user.id, ttl_days=30)
                    st.session_state["auth_user_id"] = user.id
                    st.session_state["auth_username"] = user.username
                    st.session_state["auth_onboarding_completed"] = bool(user.onboarding_completed)
                    st.session_state["auth_session_token"] = session_token
                    st.query_params["auth_token"] = session_token
                    st.rerun()
        with tab_signup:
            signup_username = st.text_input("Username (new account)", key="signup_username")
            signup_password = st.text_input("Password", type="password", key="signup_password")
            signup_password_2 = st.text_input("Confirm password", type="password", key="signup_password_2")
            st.caption("Username must be at least 3 characters. Password must be at least 8 characters.")
            if st.button("Create account"):
                if signup_password != signup_password_2:
                    st.error("Passwords do not match.")
                else:
                    try:
                        user = profile_repo.create_user_with_password(
                            username=signup_username,
                            password=signup_password,
                        )
                        st.session_state["auth_user_id"] = user.id
                        st.session_state["auth_username"] = user.username
                        st.session_state["auth_onboarding_completed"] = bool(user.onboarding_completed)
                        session_token = profile_repo.create_session(user_id=user.id, ttl_days=30)
                        st.session_state["auth_session_token"] = session_token
                        st.query_params["auth_token"] = session_token
                        st.success("Account created.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f"Could not create account: {type(exc).__name__}")
        return

    st.session_state["auth_username"] = auth_user.username
    st.session_state["auth_onboarding_completed"] = bool(auth_user.onboarding_completed)

    if (
        st.session_state.get("plan_result") is None
        and st.session_state.get("loaded_latest_plan_user_id") != auth_user.id
    ):
        latest = profile_repo.get_latest_plan(user_id=auth_user.id)
        if isinstance(latest, dict) and latest:
            st.session_state["plan_result"] = latest
            st.session_state["loaded_latest_plan_user_id"] = auth_user.id
            st.session_state["plan_build_phase"] = "ready"
            st.session_state["plan_build_summary"] = _plan_summary_from_result(latest)

    if not auth_user.onboarding_completed:
        st.subheader("Welcome! Complete onboarding")
        st.caption("Set your default preferences now, or skip and do it later from profile settings.")
        c_on_1, c_on_2 = st.columns(2)
        with c_on_1:
            if st.button("Skip for now", type="secondary"):
                profile_repo.set_onboarding_completed(user_id=auth_user.id, completed=True)
                st.session_state["auth_onboarding_completed"] = True
                st.rerun()
        with c_on_2:
            with st.form("onboarding_preferences_form"):
                pace_options = ("relaxed", "balanced", "packed")
                budget_options = ("low", "moderate", "high")
                pace_default = st.selectbox("Preferred pace", options=pace_options, index=1)
                budget_default = st.selectbox("Preferred budget", options=budget_options, index=1)
                dietary_default = st.selectbox(
                    "Preferred food style",
                    options=list(dietary_opts),
                    index=_default_index(dietary_opts, "Doesn't matter / no preference"),
                )
                mobility_default = st.selectbox(
                    "Preferred mobility",
                    options=list(mobility_opts),
                    index=_default_index(mobility_opts, "No specific needs"),
                )
                interest_default = st.multiselect("Preferred interests", options=list(get_interest_options()), default=[])
                include_acc_default = st.checkbox("Prefer accommodation suggestions by default", value=True)
                submitted = st.form_submit_button("Save preferences and continue")
                if submitted:
                    try:
                        existing = profile_repo.get_profile_by_name(
                            "Default preferences",
                            user_id=auth_user.id,
                        )
                        payload = UserProfileUpsert(
                            name="Default preferences",
                            party_size_default=2,
                            interest_tags_default=list(interest_default),
                            neighbourhoods_default=[],
                            budget_tier_default=budget_default,  # type: ignore[arg-type]
                            pace_default=pace_default,  # type: ignore[arg-type]
                            dietary_choice_default=dietary_default,
                            mobility_choice_default=mobility_default,
                            include_accommodation_default=include_acc_default,
                            extra_details_default="",
                        )
                        if existing is None:
                            profile_repo.create_profile(payload, user_id=auth_user.id)
                        else:
                            profile_repo.update_profile(existing.id, payload, user_id=auth_user.id)
                        profile_repo.set_onboarding_completed(user_id=auth_user.id, completed=True)
                        st.session_state["auth_onboarding_completed"] = True
                        st.success("Onboarding completed.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not save preferences: {type(exc).__name__}")
        return

    top_left, top_right = st.columns([0.55, 0.45], gap="large")
    with top_left:
        h1, h2 = st.columns([0.55, 0.45])
        with h1:
            st.caption(f"Signed in as `{auth_user.username}`")
        with h2:
            account_action = st.selectbox(
                "Account",
                options=["Account", "Profile settings", "Log out"],
                label_visibility="collapsed",
                key="account_action_menu",
            )
            if account_action == "Log out":
                token = str(st.session_state.get("auth_session_token", "")).strip()
                if token:
                    profile_repo.revoke_session(token=token)
                st.session_state["auth_user_id"] = None
                st.session_state["auth_username"] = ""
                st.session_state["auth_onboarding_completed"] = False
                st.session_state["auth_session_token"] = ""
                st.session_state["plan_result"] = None
                st.session_state["loaded_latest_plan_user_id"] = None
                if "auth_token" in st.query_params:
                    del st.query_params["auth_token"]
                st.session_state["account_action_menu"] = "Account"
                st.rerun()

        default_pref_profile = profile_repo.get_profile_by_name("Default preferences", user_id=auth_user.id)
        if account_action == "Profile settings":
            st.info("Profile settings")
            st.caption("You can update your saved default preferences anytime.")
            with st.form("profile_settings_form"):
                p_pace_options = ("relaxed", "balanced", "packed")
                p_budget_options = ("low", "moderate", "high")
                p_dietary_default = (
                    default_pref_profile.dietary_choice_default
                    if default_pref_profile is not None
                    else "Doesn't matter / no preference"
                )
                p_mobility_default = (
                    default_pref_profile.mobility_choice_default
                    if default_pref_profile is not None
                    else "No specific needs"
                )
                p_pace = st.selectbox(
                    "Preferred pace",
                    options=p_pace_options,
                    index=_default_index(
                        p_pace_options,
                        default_pref_profile.pace_default if default_pref_profile is not None else "balanced",
                    ),
                )
                p_budget = st.selectbox(
                    "Preferred budget",
                    options=p_budget_options,
                    index=_default_index(
                        p_budget_options,
                        default_pref_profile.budget_tier_default if default_pref_profile is not None else "moderate",
                    ),
                )
                p_dietary = st.selectbox(
                    "Preferred food style",
                    options=list(dietary_opts),
                    index=_default_index(dietary_opts, p_dietary_default),
                )
                p_mobility = st.selectbox(
                    "Preferred mobility",
                    options=list(mobility_opts),
                    index=_default_index(mobility_opts, p_mobility_default),
                )
                p_interests = st.multiselect(
                    "Preferred interests",
                    options=list(get_interest_options()),
                    default=list(default_pref_profile.interest_tags_default) if default_pref_profile else [],
                )
                p_include_acc = st.checkbox(
                    "Prefer accommodation suggestions by default",
                    value=bool(default_pref_profile.include_accommodation_default) if default_pref_profile else True,
                )
                p_saved = st.form_submit_button("Save profile preferences")
                if p_saved:
                    payload = UserProfileUpsert(
                        name="Default preferences",
                        party_size_default=2,
                        interest_tags_default=list(p_interests),
                        neighbourhoods_default=[],
                        budget_tier_default=p_budget,  # type: ignore[arg-type]
                        pace_default=p_pace,  # type: ignore[arg-type]
                        dietary_choice_default=p_dietary,
                        mobility_choice_default=p_mobility,
                        include_accommodation_default=p_include_acc,
                        extra_details_default="",
                    )
                    try:
                        existing = profile_repo.get_profile_by_name(
                            "Default preferences",
                            user_id=auth_user.id,
                        )
                        if existing is None:
                            profile_repo.create_profile(payload, user_id=auth_user.id)
                        else:
                            profile_repo.update_profile(existing.id, payload, user_id=auth_user.id)
                        st.success("Profile preferences saved.")
                        st.rerun()
                    except Exception:
                        st.error("Could not save profile preferences.")

        default_start = st.session_state.get("form_start_date", date.today())
        if not isinstance(default_start, date):
            default_start = date.today()
        default_end = st.session_state.get("form_end_date")
        if not isinstance(default_end, date):
            default_end = default_start + timedelta(days=1)
        if default_end < default_start:
            default_end = default_start
        st.subheader(str(constants.get("section_plan", "Your trip")))

        r1c1, r1c2, r1c3 = st.columns(3)
        with r1c1:
            start_date = st.date_input(
                str(constants.get("label_start_date", "Trip start date")),
                value=default_start,
                min_value=date.today(),
                format="DD-MM-YYYY",
                help=str(constants.get("help_start_date", "")),
                key="form_start_date",
            )
        with r1c2:
            end_value = default_end if default_end >= start_date else start_date
            end_date = st.date_input(
                str(constants.get("label_end_date", "Trip end date")),
                value=end_value,
                min_value=start_date,
                max_value=start_date + timedelta(days=13),
                format="DD-MM-YYYY",
                help=str(constants.get("help_end_date", "")),
                key="form_end_date",
            )
        with r1c3:
            party_size = int(
                st.number_input(
                    str(constants.get("label_party", "Party size")),
                    min_value=1,
                    max_value=20,
                    value=int(st.session_state.get("form_party_size", 2)),
                    step=1,
                    key="form_party_size",
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
                index=_default_index(pace_options, str(st.session_state.get("form_pace", "balanced"))),
                key="form_pace",
            )
        with r2c2:
            budget_tier = st.selectbox(
                str(constants.get("label_budget", "Budget")),
                options=budget_options,
                index=_default_index(budget_options, str(st.session_state.get("form_budget_tier", "moderate"))),
                key="form_budget_tier",
            )
        with r2c3:
            dietary_choice = st.selectbox(
                str(constants.get("label_dietary", "Food & diet")),
                options=list(dietary_opts),
                index=_default_index(dietary_opts, str(st.session_state.get("form_dietary_choice", "Doesn't matter / no preference"))),
                help=str(constants.get("help_dietary", "")),
                key="form_dietary_choice",
            )

        interest_options = list(get_interest_options())
        neighbourhood_options = list(get_neighbourhood_options())
        r3c1, r3c2, r3c3 = st.columns(3)
        with r3c1:
            mobility_choice = st.selectbox(
                str(constants.get("label_mobility", "Walking & getting around")),
                options=list(mobility_opts),
                index=_default_index(mobility_opts, str(st.session_state.get("form_mobility_choice", "No specific needs"))),
                help=str(constants.get("help_mobility", "")),
                key="form_mobility_choice",
            )
        with r3c2:
            interest_tags = st.multiselect(
                str(constants.get("label_interests", "Interests")),
                options=interest_options,
                default=list(st.session_state.get("form_interest_tags", [])),
                help=str(constants.get("help_interests", "")),
                key="form_interest_tags",
            )
        with r3c3:
            neighbourhoods = st.multiselect(
                str(constants.get("label_neighbourhoods", "Neighbourhoods")),
                options=neighbourhood_options,
                default=list(st.session_state.get("form_neighbourhoods", [])),
                help=str(constants.get("help_neighbourhoods", "")),
                key="form_neighbourhoods",
            )

        extra_details = st.text_area(
            str(constants.get("label_notes", "Extra context")),
            value=str(st.session_state.get("form_extra_details", "")),
            height=120,
            help=str(constants.get("help_notes", "")),
            key="form_extra_details",
        )

        default_include_acc = days >= 2
        include_accommodation = st.checkbox(
            str(constants.get("label_accommodation", "Include accommodation")),
            value=default_include_acc,
            help=str(constants.get("help_accommodation", "")),
            key="form_include_accommodation",
        )
        use_saved_preferences = st.checkbox("Use my saved preferences", value=False)
        if use_saved_preferences and default_pref_profile is None:
            st.info("No saved preferences found yet. Planning will use form selections.")

        run_clicked = st.button(str(constants.get("button_run", "Run")), type="primary")

    with top_right:
        st.subheader("Plan builder")
        status_panel = st.empty()
        summary_panel = st.empty()
        steps_panel = st.empty()
        phase = str(st.session_state.get("plan_build_phase", "idle"))
        has_existing_plan = isinstance(st.session_state.get("plan_result"), dict) and bool(st.session_state.get("plan_result"))
        if phase == "building":
            status_panel.info("Building plan...")
        elif phase == "rendering":
            status_panel.info("Finalizing and displaying your plan...")
        elif phase == "ready":
            status_panel.success("Plan ready.")
        elif phase == "error":
            status_panel.error("Plan build failed.")
        else:
            if has_existing_plan:
                status_panel.success("Plan ready.")
            else:
                status_panel.caption("Run the planner to see build progress and step logs.")
        summary_text = st.session_state.get("plan_build_summary")
        if isinstance(summary_text, str) and summary_text.strip():
            summary_panel.markdown(summary_text)
        elif has_existing_plan:
            summary_panel.markdown(_plan_summary_from_result(st.session_state.get("plan_result", {})))
        else:
            summary_panel.empty()
        completed_nodes = set(st.session_state.get("plan_build_nodes", []))
        if phase in {"building", "rendering", "ready", "error"}:
            steps_panel.markdown(_build_steps_markdown(completed_nodes, phase=phase))
        elif has_existing_plan:
            steps_panel.markdown(_build_steps_markdown(set(_NODE_TO_PHASE.keys()), phase="ready"))
        else:
            steps_panel.empty()

    if run_clicked:
        st.session_state["plan_build_phase"] = "building"
        st.session_state["plan_build_nodes"] = []
        effective_party_size = party_size
        effective_interest_tags = list(interest_tags)
        effective_neighbourhoods = list(neighbourhoods)
        effective_budget_tier = budget_tier
        effective_pace = pace
        effective_dietary_choice = dietary_choice
        effective_mobility_choice = mobility_choice
        effective_include_accommodation = include_accommodation
        effective_extra_details = extra_details
        prefs_applied = bool(use_saved_preferences and default_pref_profile is not None)
        if prefs_applied and default_pref_profile is not None:
            effective_party_size = int(default_pref_profile.party_size_default)
            effective_interest_tags = list(default_pref_profile.interest_tags_default)
            # Districts are intentionally not part of saved preferences; keep current form choice.
            effective_neighbourhoods = list(neighbourhoods)
            effective_budget_tier = default_pref_profile.budget_tier_default
            effective_pace = default_pref_profile.pace_default
            effective_dietary_choice = default_pref_profile.dietary_choice_default
            effective_mobility_choice = default_pref_profile.mobility_choice_default
            effective_include_accommodation = bool(default_pref_profile.include_accommodation_default)
            if str(default_pref_profile.extra_details_default).strip():
                effective_extra_details = str(default_pref_profile.extra_details_default).strip()

        interests_short = ", ".join(effective_interest_tags[:2]) + (
            f" +{len(effective_interest_tags) - 2} more" if len(effective_interest_tags) > 2 else ""
        )
        areas_short = ", ".join(effective_neighbourhoods[:2]) + (
            f" +{len(effective_neighbourhoods) - 2} more" if len(effective_neighbourhoods) > 2 else ""
        )
        start_label = start_date.strftime("%d-%m-%Y")
        end_label = end_date.strftime("%d-%m-%Y")
        summary_lines = [
            f"**Dates:** {start_label} to {end_label}.",
            f"**Trip summary:** {days} day(s), {effective_party_size} traveler(s), {effective_pace} pace, {effective_budget_tier} budget.",
            f"**Food/mobility:** {effective_dietary_choice}; {effective_mobility_choice}.",
            f"**Accommodation:** {'requested' if effective_include_accommodation else 'not requested'}.",
        ]
        summary_lines.append(f"**Preference mode:** {'saved preferences applied' if prefs_applied else 'form selections only'}.")
        if interests_short:
            summary_lines.append(f"**Interests:** {interests_short}.")
        if areas_short:
            summary_lines.append(f"**Areas:** {areas_short}.")
        summary_text = "  \n".join(summary_lines)
        st.session_state["plan_build_summary"] = summary_text
        summary_panel.markdown(summary_text)
        profile = TripProfile(
            days=days,
            start_date=start_date,
            end_date=end_date,
            party_size=effective_party_size,
            interest_tags=effective_interest_tags,
            neighbourhoods=effective_neighbourhoods,
            budget_tier=effective_budget_tier,  # type: ignore[arg-type]
            pace=effective_pace,  # type: ignore[arg-type]
            dietary_choice=effective_dietary_choice,
            mobility_choice=effective_mobility_choice,
            include_accommodation=effective_include_accommodation,
            extra_details=effective_extra_details,
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
        profile_repo.save_latest_plan(user_id=auth_user.id, plan=result)
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
    events_items = list(result.get("events_items", []))
    events_message = str(result.get("events_message", "")).strip()
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
            st.caption(f"Trip dates: {_format_display_date(trip_start)} to {_format_display_date(trip_end)}")
        weather_summary = str(result.get("weather_summary", "")).strip()
        weather_bias = str(result.get("weather_bias", "unknown"))
        weather_condition_main = str(result.get("weather_condition_main", ""))
        practical_notes = itinerary.get("practical_notes", []) if isinstance(itinerary, dict) else []
        preview_tabs = st.tabs(["🗓️ Berlin Itinerary", "🌤️ Weather", "📝 Practical Notes", "🎟️ Events"])

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
                shown_note = False
                for note in practical_notes:
                    text = str(note).strip()
                    if text and _is_user_facing_practical_note(text):
                        st.markdown(f"- {text}")
                        shown_note = True
                if not shown_note:
                    st.caption("No practical notes were generated for this run.")
            else:
                st.caption("No practical notes were generated for this run.")

        with preview_tabs[3]:
            if events_items:
                for row in events_items[:4]:
                    if not isinstance(row, dict):
                        continue
                    ev_name = str(row.get("name", "")).strip()
                    ev_date = _format_display_date(str(row.get("start_local", "")).strip())
                    ev_venue = str(row.get("venue", "")).strip()
                    ev_url = str(row.get("url", "")).strip()
                    parts = [p for p in [ev_date, ev_venue] if p]
                    tail = " · ".join(parts)
                    if ev_url:
                        st.markdown(f"- **{ev_name}** — {tail} ([link]({ev_url}))")
                    else:
                        st.markdown(f"- **{ev_name}** — {tail}")
            else:
                st.caption(events_message or "No events available for the selected dates.")

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
                            best_name = str(best.get("name", "Nearest stop"))
                            best_modes = best.get("modes", [])
                            if not isinstance(best_modes, list):
                                fallback_mode = str(best.get("mode", ""))
                                best_modes = [fallback_mode] if fallback_mode else []
                            best_icon = _transport_mode_icons_html(best_modes)
                            st.markdown(
                                f"**Best option:** {best_icon}{best_name} — {_walk_hint(best.get('distance_m'))}",
                                unsafe_allow_html=True,
                            )
                        with st.expander("See additional nearby options", expanded=False):
                            for idx, opt in enumerate(options):
                                if not isinstance(opt, dict):
                                    continue
                                if idx == 0:
                                    continue
                                opt_name = str(opt.get("name", "Unknown stop"))
                                opt_modes = opt.get("modes", [])
                                if not isinstance(opt_modes, list):
                                    fallback_mode = str(opt.get("mode", ""))
                                    opt_modes = [fallback_mode] if fallback_mode else []
                                opt_icon = _transport_mode_icons_html(opt_modes)
                                st.markdown(
                                    f"- {opt_icon}{opt_name} — {_walk_hint(opt.get('distance_m'))}",
                                    unsafe_allow_html=True,
                                )
                    else:
                        st.caption("No nearby stop details available for this place.")
                    st.divider()
            elif transport_items:
                for item in transport_items[:10]:
                    distance = item.get("distance_m")
                    distance_text = _walk_hint(distance if isinstance(distance, (int, float)) else None)
                    modes = item.get("modes", [])
                    if not isinstance(modes, list):
                        fallback_mode = str(item.get("mode", ""))
                        modes = [fallback_mode] if fallback_mode else []
                    icon = _transport_mode_icons_html(modes)
                    st.markdown(
                        f"- {icon}<strong>{item.get('name','')}</strong> — near {item.get('query','')} ({distance_text})",
                        unsafe_allow_html=True,
                    )
            else:
                transport_msg = str(result.get("transport_message", "")).strip()
                if transport_msg:
                    st.caption("Transportation info is not available right now. Please try again shortly.")
                else:
                    st.caption("No transport suggestions available for this run.")

        with tabs[3]:
            if accommodation_items:
                for idx, item in enumerate(accommodation_items[:5]):
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
                            st.markdown(
                                (
                                    '<img src="'
                                    + html.escape(photo_url, quote=True)
                                    + '" alt="Accommodation thumbnail" '
                                    + 'style="width:180px;height:120px;object-fit:cover;object-position:center;'
                                    + 'border-radius:10px;display:block;margin-bottom:6px;" />'
                                ),
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown(
                                '<div style="width:180px;height:120px;border-radius:10px;'
                                'background:#f2f4f7;color:#667085;display:flex;align-items:center;'
                                'justify-content:center;font-size:12px;">No photo</div>',
                                unsafe_allow_html=True,
                            )
                    with c_txt:
                        st.markdown(
                            f"- **{name}** ({typ}, {district}) — {reason}  \n"
                            f"  - {rating_text}  \n"
                            f"  - {address} {link}",
                            unsafe_allow_html=True,
                        )
                    if idx < min(5, len(accommodation_items)) - 1:
                        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
            else:
                st.caption("Accommodation suggestions are not enabled for this run.")

        with tabs[4]:
            with st.expander("Raw Data", expanded=False):
                st.json(result)

            with st.expander("Structured Itinerary (JSON)", expanded=False):
                if isinstance(itinerary, dict) and itinerary:
                    st.json(itinerary)
                else:
                    st.caption("No itinerary JSON for this run.")

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




if __name__ == "__main__":
    main()
