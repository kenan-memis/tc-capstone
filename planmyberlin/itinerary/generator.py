"""LLM-backed itinerary generation with structured output and grounding checks."""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from planmyberlin.config.loader import get_settings
from planmyberlin.itinerary.grounding import (
    candidate_name_allowlist,
    find_grounding_violations,
    sanitize_place_names,
)
from planmyberlin.itinerary.models import TripItinerary
from planmyberlin.prompts.loader import render_prompt


def _fallback_itinerary(*, days: int, weather_summary: str, candidates: list[dict[str, Any]]) -> TripItinerary:
    names = [str(x.get("name", "")).strip() for x in candidates if str(x.get("name", "")).strip()]
    title = f"{days}-day Berlin preview plan"
    out_days: list[dict[str, Any]] = []
    for d in range(1, max(1, days) + 1):
        act = []
        if names:
            act.append(
                {
                    "time_of_day": "morning",
                    "title": f"Explore {names[(d - 1) % len(names)]}",
                    "description": "Walk the area and visit nearby cafés or viewpoints.",
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
    notes = [f"Weather context: {weather_summary}"]
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
    user_prompt = render_prompt(
        "itinerary",
        "user",
        profile_json=json.dumps(profile, ensure_ascii=False, indent=2),
        context_json=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    system_prompt = render_prompt("itinerary", "system")

    if not os.getenv("OPENAI_API_KEY"):
        it = _fallback_itinerary(
            days=days,
            weather_summary=str(state.get("weather_summary", "Weather unavailable.")),
            candidates=candidates,
        )
        return {
            "itinerary_status": "fallback",
            "itinerary": it.model_dump(),
            "itinerary_message": "OPENAI_API_KEY not set; showing a deterministic preview plan.",
        }

    try:
        llm = ChatOpenAI(model=model, temperature=temperature)
        structured = llm.with_structured_output(TripItinerary)
        out: TripItinerary = structured.invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )

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
        )
        return {
            "itinerary_status": "fallback",
            "itinerary": it.model_dump(),
            "itinerary_message": f"Itinerary LLM unavailable ({type(exc).__name__}); showing preview plan.",
        }
