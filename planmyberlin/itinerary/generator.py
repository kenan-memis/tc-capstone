"""LLM-backed itinerary generation with structured output and grounding checks."""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from planmyberlin.config.loader import get_settings
from planmyberlin.itinerary.constraints import (
    enforce_day_count,
    format_constraint_instructions,
    neighbourhood_coverage_note,
    strip_itinerary_timing,
)
from planmyberlin.itinerary.grounding import (
    candidate_name_allowlist,
    find_grounding_violations,
    sanitize_place_names,
)
from planmyberlin.itinerary.models import TripItinerary
from planmyberlin.itinerary.tool_loop import run_itinerary_tool_loop
from planmyberlin.itinerary.tools import build_itinerary_tools
from planmyberlin.observability import get_logger
from planmyberlin.prompts.loader import render_prompt

_log = get_logger(__name__)


def _is_local_candidate(item: dict[str, Any], selected_areas: list[str]) -> bool:
    if not selected_areas:
        return True
    district = str(item.get("district", "")).strip().lower()
    name = str(item.get("name", "")).strip().lower()
    hay = f"{district} {name}".strip()
    return any(area in hay or hay in area for area in selected_areas if area)


def _hybrid_activity_title(slot: str, place_name: str) -> str:
    s = (slot or "").strip().lower()
    if s == "morning":
        return f"Morning exploration at {place_name}"
    if s == "afternoon":
        return f"Afternoon visit at {place_name}"
    if s == "evening":
        return f"Evening around {place_name}"
    return f"Explore {place_name}"


def _hybrid_activity_description(slot: str, *, nearby: bool) -> str:
    s = (slot or "").strip().lower()
    if nearby:
        return (
            "Selected district options were limited for this slot, so this nearby popular option was added."
        )
    if s == "morning":
        return "Start the day with a focused visit in the selected area."
    if s == "afternoon":
        return "Use this slot for a core attraction with flexible pacing."
    if s == "evening":
        return "Wrap up the day with a relaxed activity and dinner nearby."
    return "Flexible activity aligned with your selected area."


def _apply_hybrid_slot_fallback(
    itinerary: TripItinerary,
    *,
    profile: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> TripItinerary:
    selected = [str(x).strip().lower() for x in profile.get("neighbourhoods", []) if str(x).strip()]
    used_names = {
        str(a.place_name).strip().lower()
        for d in itinerary.days
        for a in d.activities
        if str(a.place_name or "").strip()
    }
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        key = name.lower()
        if key in seen or key in used_names:
            continue
        seen.add(key)
        deduped.append(item)

    local_pool = [x for x in deduped if _is_local_candidate(x, selected)]
    nearby_pool = [x for x in deduped if x not in local_pool]
    local_idx = 0
    nearby_idx = 0
    used_nearby = False

    new_days: list[Any] = []
    for day in itinerary.days:
        acts: list[Any] = []
        for act in day.activities:
            if str(act.place_name or "").strip():
                acts.append(act)
                continue
            pick: dict[str, Any] | None = None
            nearby = False
            if local_idx < len(local_pool):
                pick = local_pool[local_idx]
                local_idx += 1
            elif nearby_idx < len(nearby_pool):
                pick = nearby_pool[nearby_idx]
                nearby_idx += 1
                nearby = True
                used_nearby = True
            if not pick:
                acts.append(act)
                continue
            place_name = str(pick.get("name", "")).strip()
            acts.append(
                {
                    "time_of_day": act.time_of_day,
                    "title": _hybrid_activity_title(act.time_of_day, place_name),
                    "description": _hybrid_activity_description(act.time_of_day, nearby=nearby),
                    "place_name": place_name,
                }
            )
        new_days.append({"day_number": day.day_number, "theme": day.theme, "activities": acts})

    notes = list(itinerary.practical_notes)
    if used_nearby:
        note = "Limited matches in selected areas, so nearby popular options were added."
        if note not in notes:
            notes.append(note)
    return TripItinerary.model_validate({"title": itinerary.title, "days": new_days, "practical_notes": notes})


def _fallback_itinerary(
    *,
    days: int,
    weather_summary: str,
    candidates: list[dict[str, Any]],
    profile: dict[str, Any],
) -> TripItinerary:
    names = [str(x.get("name", "")).strip() for x in candidates if str(x.get("name", "")).strip()]
    pace = str(profile.get("pace", "balanced"))
    mobility = str(profile.get("mobility_choice", ""))
    dietary = str(profile.get("dietary_choice", ""))
    title = f"{days}-day Berlin preview plan"
    out_days: list[dict[str, Any]] = []
    for d in range(1, max(1, days) + 1):
        act = []
        if names:
            pace_note = {"relaxed": " slower pacing", "packed": " tighter pacing", "balanced": ""}.get(pace, "")
            act.append(
                {
                    "time_of_day": "morning",
                    "title": f"Explore {names[(d - 1) % len(names)]}",
                    "description": (
                        f"Walk the area with{pace_note}; consider mobility preference ({mobility}). "
                        f"For meals, respect dietary preference ({dietary}) when choosing candidates."
                    ),
                    "place_name": names[(d - 1) % len(names)],
                }
            )
        act.append(
            {
                "time_of_day": "afternoon",
                "title": "Flexible afternoon",
                "description": "Keep plans flexible based on energy and weather.",
                "place_name": None,
            }
        )
        out_days.append({"day_number": d, "theme": f"Day {d} highlights", "activities": act})
    notes = [
        f"Weather context: {weather_summary}",
        f"Pace: {pace}; mobility hint: {mobility}; dietary: {dietary}.",
    ]
    if not names:
        notes.append("No specific candidate places were available; add interests or neighbourhoods for tighter suggestions.")
    return TripItinerary.model_validate({"title": title, "days": out_days, "practical_notes": notes})


def generate_itinerary(state: dict[str, Any]) -> dict[str, Any]:
    """Return dict with itinerary_status, itinerary (dict), itinerary_message."""
    settings = get_settings()
    llm_cfg = settings.get("itinerary", {})
    model = str(llm_cfg.get("model", "gpt-4o-mini"))
    temperature = float(llm_cfg.get("temperature", 0.4))
    grounding_repair = bool(llm_cfg.get("grounding_repair", True))
    tool_use = bool(llm_cfg.get("tool_use", False))
    tool_max_rounds = max(1, min(int(llm_cfg.get("tool_max_rounds", 6)), 16))

    profile = state.get("profile", {})
    if not isinstance(profile, dict):
        return {
            "itinerary_status": "unavailable",
            "itinerary": {},
            "itinerary_message": "Profile missing for itinerary generation.",
        }

    days = int(profile.get("days", 1))
    candidates = list(state.get("enriched_items", [])) or list(state.get("retrieved_items", []))
    allowed_norm, norm_to_canonical = candidate_name_allowlist(candidates)
    allowed_display = list(norm_to_canonical.values())

    payload = {
        "profile": profile,
        "weather_summary": state.get("weather_summary", ""),
        "weather_bias": state.get("weather_bias", "unknown"),
        "transport_items": state.get("transport_items", []),
        "accommodation_items": state.get("accommodation_items", []),
        "candidates": candidates[:12],
    }
    constraint_bullets = format_constraint_instructions(profile)
    user_prompt = render_prompt(
        "itinerary",
        "user",
        profile_json=json.dumps(profile, ensure_ascii=False, indent=2),
        constraint_bullets=constraint_bullets,
        context_json=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    system_prompt = render_prompt("itinerary", "system")

    if not os.getenv("OPENAI_API_KEY"):
        it = _fallback_itinerary(
            days=days,
            weather_summary=str(state.get("weather_summary", "Weather unavailable.")),
            candidates=candidates,
            profile=profile,
        )
        it, _ = enforce_day_count(it, days)
        it = _apply_hybrid_slot_fallback(it, profile=profile, candidates=candidates)
        it = neighbourhood_coverage_note(profile, it)
        return {
            "itinerary_status": "fallback",
            "itinerary": it.model_dump(),
            "itinerary_message": "OPENAI_API_KEY not set; showing a deterministic preview plan.",
        }

    try:
        llm = ChatOpenAI(model=model, temperature=temperature)

        scratchpad = ""
        if tool_use:
            try:
                tools = build_itinerary_tools(state)
                tool_system = render_prompt("itinerary_tools", "system")
                tool_human = render_prompt(
                    "itinerary_tools",
                    "user",
                    profile_json=json.dumps(profile, ensure_ascii=False, indent=2),
                    constraint_bullets=constraint_bullets,
                )
                scratchpad = run_itinerary_tool_loop(
                    llm,
                    tools,
                    system=tool_system,
                    human=tool_human,
                    max_rounds=tool_max_rounds,
                )
            except Exception as exc:
                _log.warning(
                    "itinerary_tool_phase_failed exc_type=%s — continuing without scratchpad",
                    type(exc).__name__,
                    exc_info=True,
                )

        user_prompt_final = user_prompt
        if scratchpad:
            user_prompt_final = (
                user_prompt
                + "\n\n## Analyst checklist (tool-assisted — honor unless it conflicts with schema or constraints)\n"
                + scratchpad
            )

        structured = llm.with_structured_output(TripItinerary)
        out: TripItinerary = structured.invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt_final)]
        )

        out = strip_itinerary_timing(out)
        out, _struct_changed = enforce_day_count(out, days)
        out = _apply_hybrid_slot_fallback(out, profile=profile, candidates=candidates)
        out = neighbourhood_coverage_note(profile, out)

        violations = find_grounding_violations(out, allowed_norm)
        if violations:
            if grounding_repair and os.getenv("OPENAI_API_KEY"):
                try:
                    repair_user = render_prompt(
                        "itinerary_repair",
                        "user",
                        allowed_names_json=json.dumps(allowed_display, ensure_ascii=False, indent=2),
                        violations_json=json.dumps(
                            [
                                {
                                    "day_number": v.day_number,
                                    "activity_index": v.activity_index,
                                    "place_name": v.place_name,
                                }
                                for v in violations
                            ],
                            ensure_ascii=False,
                            indent=2,
                        ),
                        itinerary_json=json.dumps(out.model_dump(), ensure_ascii=False, indent=2),
                    )
                    repair_system = render_prompt("itinerary_repair", "system")
                    out = structured.invoke(
                        [SystemMessage(content=repair_system), HumanMessage(content=repair_user)]
                    )
                    out = strip_itinerary_timing(out)
                    out, _ = enforce_day_count(out, days)
                    out = _apply_hybrid_slot_fallback(out, profile=profile, candidates=candidates)
                    out = neighbourhood_coverage_note(profile, out)
                    violations = find_grounding_violations(out, allowed_norm)
                    if not violations:
                        return {
                            "itinerary_status": "ok_repaired",
                            "itinerary": out.model_dump(),
                            "itinerary_message": "Venue names were aligned with retrieved candidates.",
                        }
                except Exception:
                    pass

            out = sanitize_place_names(out, allowed_norm, norm_to_canonical)
            out = strip_itinerary_timing(out)
            out, _ = enforce_day_count(out, days)
            out = _apply_hybrid_slot_fallback(out, profile=profile, candidates=candidates)
            out = neighbourhood_coverage_note(profile, out)
            return {
                "itinerary_status": "grounded_sanitized",
                "itinerary": out.model_dump(),
                "itinerary_message": "Some venue references were adjusted to match retrieved candidates only.",
            }

        return {"itinerary_status": "ok", "itinerary": out.model_dump(), "itinerary_message": "ok"}
    except Exception as exc:
        it = _fallback_itinerary(
            days=days,
            weather_summary=str(state.get("weather_summary", "Weather unavailable.")),
            candidates=candidates,
            profile=profile,
        )
        it, _ = enforce_day_count(it, days)
        it = _apply_hybrid_slot_fallback(it, profile=profile, candidates=candidates)
        it = neighbourhood_coverage_note(profile, it)
        return {
            "itinerary_status": "fallback",
            "itinerary": it.model_dump(),
            "itinerary_message": f"Itinerary LLM unavailable ({type(exc).__name__}); showing preview plan.",
        }
