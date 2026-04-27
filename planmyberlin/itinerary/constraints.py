"""Trip-profile constraints for itinerary prompts and light structural validation."""

from __future__ import annotations

import re
from typing import Any

from planmyberlin.itinerary.models import ItineraryActivity, ItineraryDay, TripItinerary


def format_constraint_instructions(profile: dict[str, Any]) -> str:
    """Human-readable bullets appended to the itinerary user prompt."""
    days = int(profile.get("days", 1))
    pace = str(profile.get("pace", "balanced"))
    dietary = str(profile.get("dietary_choice", ""))
    mobility = str(profile.get("mobility_choice", ""))
    budget = str(profile.get("budget_tier", "moderate"))
    party = int(profile.get("party_size", 2))
    interests = profile.get("interest_tags", [])
    neighbourhoods = profile.get("neighbourhoods", [])
    extra = str(profile.get("extra_details", "")).strip()

    pace_hints = {
        "relaxed": "Fewer stops per day, longer breaks, slower starts; avoid cramming.",
        "balanced": "Mix anchor sights with flexible blocks; one main activity block morning and one afternoon/evening.",
        "packed": "More stops possible but still realistic walking; avoid minute-by-minute schedules.",
    }
    pace_hint = pace_hints.get(pace, pace_hints["balanced"])

    flex_budget = max(0, days - 2) if days >= 3 else 0
    uniq_rule = (
        "- **Venue names:** use each candidate venue at most once in the entire trip (no repeats). "
        "If the trip is **1–2 days**, every morning/afternoon/evening slot should name a distinct venue when candidates allow. "
        + (
            f"- **Flexible outdoor blocks:** for trips of **3+ days**, allow **{flex_budget}** afternoon slot(s) "
            "(from day 3 onward) as weather-friendly walking/biking/park time **without** naming a single venue."
            if flex_budget
            else ""
        )
    )

    lines: list[str] = [
        f"- **Trip length:** produce exactly **{days}** calendar day(s). The `days` array must have length **{days}** with `day_number` **1** through **{days}** (one object per day).",
        uniq_rule,
        f"- **Pace ({pace}):** {pace_hint}",
        f"- **Budget style ({budget}):** bias restaurant/café suggestions accordingly (simple language only; no prices unless from candidates).",
        f"- **Party size ({party}):** mention group-friendly pacing if party > 2 (e.g. seating, simpler logistics).",
        f"- **Dietary ({dietary}):** when you choose food venues from candidates, align meal ideas with this preference. If the label implies no preference, stay neutral.",
        f"- **Mobility / getting around ({mobility}):** prefer shorter walking segments, fewer stairs, calmer routes when mobility suggests it; never guarantee step-free access at every venue.",
    ]
    if isinstance(interests, list) and interests:
        lines.append(
            f"- **Interests:** reflect these themes across the days: {', '.join(str(x) for x in interests)}."
        )
    if isinstance(neighbourhoods, list) and neighbourhoods:
        lines.append(
            f"- **Neighbourhoods:** bias daily themes and routing toward these areas when candidates allow: {', '.join(str(x) for x in neighbourhoods)}. "
            "At least one day theme or practical note should mention exploring one of these areas by name."
        )
    else:
        lines.append("- **Neighbourhoods:** none selected — keep geography sensible with candidates and weather.")
    if extra:
        lines.append(f"- **Other details (from traveler):** incorporate when consistent with candidates: {extra}")
    return "\n".join(lines)


def _normalize(s: str) -> str:
    return " ".join(s.lower().split())


def _fill_day_slots(activities: list[ItineraryActivity], *, day_number: int) -> list[ItineraryActivity]:
    by_slot: dict[str, ItineraryActivity] = {}
    for act in activities:
        slot = str(act.time_of_day).strip().lower()
        if slot in {"morning", "afternoon", "evening"} and slot not in by_slot:
            by_slot[slot] = act

    if "morning" not in by_slot:
        by_slot["morning"] = ItineraryActivity(
            time_of_day="morning",
            title="Morning neighborhood walk",
            description="Start the day with a relaxed walk and coffee in your selected area.",
            place_name=None,
        )
    if "afternoon" not in by_slot:
        by_slot["afternoon"] = ItineraryActivity(
            time_of_day="afternoon",
            title="Flexible exploration",
            description="Explore nearby highlights based on your energy and current conditions.",
            place_name=None,
        )
    if "evening" not in by_slot:
        by_slot["evening"] = ItineraryActivity(
            time_of_day="evening",
            title=f"Evening in Berlin (Day {day_number})",
            description="Wrap up the day with dinner or a scenic evening stroll.",
            place_name=None,
        )

    return [by_slot["morning"], by_slot["afternoon"], by_slot["evening"]]


def enforce_day_count(itinerary: TripItinerary, expected_days: int) -> tuple[TripItinerary, bool]:
    """Ensure `days` length matches expected_days with day_number 1..N. Returns (updated, changed)."""
    expected_days = max(1, min(14, int(expected_days)))
    sorted_days = sorted(itinerary.days, key=lambda d: d.day_number)
    changed = False

    if len(sorted_days) > expected_days:
        sorted_days = sorted_days[:expected_days]
        changed = True

    new_days: list[ItineraryDay] = []
    for i in range(1, expected_days + 1):
        if i - 1 < len(sorted_days):
            d = sorted_days[i - 1]
            if d.day_number != i:
                changed = True
            new_days.append(
                ItineraryDay(
                    day_number=i,
                    theme=d.theme if str(d.theme).strip() else f"Day {i}",
                    activities=_fill_day_slots(list(d.activities), day_number=i),
                )
            )
            if len(d.activities) != 3:
                changed = True
        else:
            changed = True
            new_days.append(
                ItineraryDay(
                    day_number=i,
                    theme=f"Day {i}",
                    activities=_fill_day_slots([], day_number=i),
                )
            )

    out = TripItinerary(title=itinerary.title, days=new_days, practical_notes=list(itinerary.practical_notes))
    return out, changed


def neighbourhood_coverage_note(profile: dict[str, Any], itinerary: TripItinerary) -> TripItinerary:
    """If neighbourhoods were selected but none appear in themes/notes, append a gentle reminder."""
    nh = profile.get("neighbourhoods", [])
    if not isinstance(nh, list) or not nh:
        return itinerary

    blob = _normalize(itinerary.title + " " + " ".join(d.theme for d in itinerary.days))
    blob += " " + _normalize(" ".join(str(n) for n in itinerary.practical_notes))
    for n in nh:
        if _normalize(str(n)) in blob:
            return itinerary

    notes = list(itinerary.practical_notes)
    notes.append(f"Consider spending time in: {', '.join(str(x) for x in nh)} — daily themes can lean that way when candidates align.")
    return TripItinerary(title=itinerary.title, days=list(itinerary.days), practical_notes=notes)


def strip_timing_claims(text: str) -> str:
    """Remove patterns like '10:30' or 'at 14:00' from free text (light guardrail)."""
    text = re.sub(r"\b\d{1,2}:\d{2}\b", "", text)
    text = re.sub(r"\bat\s+\d{1,2}\s*(am|pm)\b", "", text, flags=re.I)
    return " ".join(text.split())


def strip_itinerary_timing(itinerary: TripItinerary) -> TripItinerary:
    """Remove clock-style times from titles/descriptions/themes (no exact schedules)."""
    new_days: list[ItineraryDay] = []
    for d in itinerary.days:
        acts: list[ItineraryActivity] = []
        for a in d.activities:
            acts.append(
                ItineraryActivity(
                    time_of_day=a.time_of_day,
                    title=strip_timing_claims(a.title),
                    description=strip_timing_claims(a.description),
                    place_name=a.place_name,
                )
            )
        new_days.append(
            ItineraryDay(
                day_number=d.day_number,
                theme=strip_timing_claims(d.theme),
                activities=acts,
            )
        )
    return TripItinerary(
        title=strip_timing_claims(itinerary.title),
        days=new_days,
        practical_notes=list(itinerary.practical_notes),
    )
