"""Unique venue assignment and flexible (non-venue) slots for multi-day itineraries."""

from __future__ import annotations

from typing import Any

from planmyberlin.itinerary.grounding import candidate_name_allowlist
from planmyberlin.itinerary.models import ItineraryActivity, ItineraryDay, TripItinerary


def merge_retrieval_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge enriched + retrieved items, preserving first-seen order and unique names."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("enriched_items", "retrieved_items"):
        raw = state.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            k = name.lower()
            if k in seen:
                continue
            seen.add(k)
            merged.append(item)
    return merged


def flexible_slot_budget(days: int) -> int:
    """Trips of 1–2 days: no flexible slots. From 3 days up: one flexible afternoon per day from day 3 onward."""
    d = max(1, int(days))
    if d <= 2:
        return 0
    return max(0, d - 2)


def _flex_positions(days: int, budget: int) -> set[tuple[int, str]]:
    """Afternoon slots on days 3..(2+budget) — exactly `budget` slots when days >= 3."""
    out: set[tuple[int, str]] = set()
    if budget <= 0:
        return out
    for i in range(budget):
        day_num = 3 + i
        if day_num <= days:
            out.add((day_num, "afternoon"))
    return out


def _is_local_candidate(item: dict[str, Any], selected_areas: list[str]) -> bool:
    if not selected_areas:
        return True
    district = str(item.get("district", "")).strip().lower()
    name = str(item.get("name", "")).strip().lower()
    hay = f"{district} {name}".strip()
    return any(area in hay or hay in area for area in selected_areas if area)


def _is_foodish(item: dict[str, Any]) -> bool:
    cat = str(item.get("category", "")).lower()
    intent = str(item.get("intent", "")).lower()
    hay = f"{cat} {intent}"
    return any(x in hay for x in ("food", "restaurant", "cafe", "coffee", "drink", "dining", "eat", "meal", "bar"))


def _profile_wants_food(profile: dict[str, Any]) -> bool:
    tags = profile.get("interest_tags") or []
    if not isinstance(tags, list):
        return False
    blob = " ".join(str(t).lower() for t in tags)
    return any(x in blob for x in ("food", "dining", "restaurant", "cafe", "coffee", "drink", "eat"))


def _hybrid_title(slot: str, place_name: str) -> str:
    s = (slot or "").strip().lower()
    if s == "morning":
        return f"Morning exploration at {place_name}"
    if s == "afternoon":
        return f"Afternoon visit at {place_name}"
    if s == "evening":
        return f"Evening around {place_name}"
    return f"Explore {place_name}"


def _hybrid_description(slot: str, *, nearby: bool) -> str:
    if nearby:
        return (
            "Selected district options were limited for this slot, so this nearby popular option was added."
        )
    s = (slot or "").strip().lower()
    if s == "morning":
        return "Start the day with a focused visit in the selected area."
    if s == "afternoon":
        return "Use this slot for a core attraction with flexible pacing."
    if s == "evening":
        return "Wrap up the day with a relaxed meal or scenic evening nearby."
    return "Flexible activity aligned with your selected area."


def _normalize(p: str) -> str:
    return " ".join(p.lower().strip().split())


def _snap_place_name(
    place_name: str | None,
    allowed_norm: set[str],
    norm_to_canonical: dict[str, str],
) -> str | None:
    if place_name is None or not str(place_name).strip():
        return None
    pn = _normalize(str(place_name))
    if pn in norm_to_canonical:
        return norm_to_canonical[pn]
    for a in allowed_norm:
        if not a:
            continue
        if a in pn or pn in a:
            return norm_to_canonical.get(a)
    return None


def _flexible_activity(
    *,
    time_of_day: str,
    weather_bias: str,
    flex_index: int,
) -> ItineraryActivity:
    bias = (weather_bias or "unknown").lower()
    outdoor_ok = bias not in ("indoor", "indoor_heavy", "indoor-heavy", "indoor only")
    if outdoor_ok:
        templates = [
            (
                "Easy bike stretch",
                "A short ride on Berlin bike lanes when the weather feels right.",
            ),
            (
                "Relaxed walk & explore",
                "Explore on foot and pause where it feels right.",
            ),
            (
                "Park or riverside time",
                "Low-key outdoor time — adjust to today's forecast.",
            ),
        ]
    else:
        templates = [
            (
                "Light neighborhood stroll",
                "Short walks between covered stops if conditions are wet or cold.",
            ),
            (
                "Easy indoor-to-indoor pacing",
                "Keep transitions short and favor covered routes.",
            ),
        ]
    title, desc = templates[flex_index % len(templates)]
    return ItineraryActivity(
        time_of_day=time_of_day,
        title=title,
        description=desc,
        place_name=None,
    )


def _pick_from_pool(
    pool: list[dict[str, Any]],
    used_norm: set[str],
    *,
    prefer_food: bool,
) -> tuple[dict[str, Any] | None, bool]:
    """Pick one unused item from pool (removed in-place). Prefer food venues when prefer_food is True."""
    eligible = [
        i
        for i, it in enumerate(pool)
        if _normalize(str(it.get("name", ""))) not in used_norm
    ]
    if not eligible:
        return None, False

    def score(item: dict[str, Any]) -> tuple[int, int]:
        food = _is_foodish(item)
        if prefer_food:
            return (2 if food else 0, 1 if food else 0)
        return (2 if not food else 0, 1 if not food else 0)

    best_i = max(eligible, key=lambda i: score(pool[i]))
    item = pool.pop(best_i)
    return item, True


def apply_unique_place_policy(
    itinerary: TripItinerary,
    *,
    profile: dict[str, Any],
    candidates: list[dict[str, Any]],
    weather_bias: str = "",
) -> TripItinerary:
    """
    Enforce trip-wide unique venue names, optional flexible non-venue slots for longer trips,
    and fill remaining slots from the candidate pool (local first, then city-wide).
    """
    days = len(itinerary.days)
    budget = flexible_slot_budget(days)
    flex_coords = _flex_positions(days, budget)

    selected = [str(x).strip().lower() for x in profile.get("neighbourhoods", []) if str(x).strip()]
    allowed_norm, norm_to_canonical = candidate_name_allowlist(candidates)

    local: list[dict[str, Any]] = []
    nearby: list[dict[str, Any]] = []
    seen_build: set[str] = set()
    for item in candidates:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        k = name.lower()
        if k in seen_build:
            continue
        seen_build.add(k)
        if _is_local_candidate(item, selected):
            local.append(dict(item))
        else:
            nearby.append(dict(item))

    pool_local = list(local)
    pool_nearby = list(nearby)
    used_norm: set[str] = set()
    used_nearby_fill = False
    shortage_note = False

    flex_counter = 0
    new_days: list[ItineraryDay] = []

    for day in sorted(itinerary.days, key=lambda d: d.day_number):
        acts_out: list[ItineraryActivity] = []
        slot_order = {"morning": 0, "afternoon": 1, "evening": 2}
        activities = sorted(day.activities, key=lambda a: slot_order.get(str(a.time_of_day).lower(), 99))

        for act in activities:
            slot = str(act.time_of_day).strip().lower()
            if (day.day_number, slot) in flex_coords:
                acts_out.append(
                    _flexible_activity(
                        time_of_day=act.time_of_day,
                        weather_bias=weather_bias,
                        flex_index=flex_counter,
                    )
                )
                flex_counter += 1
                continue

            canon = _snap_place_name(act.place_name, allowed_norm, norm_to_canonical)
            if canon and _normalize(canon) not in used_norm:
                used_norm.add(_normalize(canon))
                acts_out.append(
                    ItineraryActivity(
                        time_of_day=act.time_of_day,
                        title=act.title,
                        description=act.description,
                        place_name=canon,
                    )
                )
                continue

            prefer_food = _profile_wants_food(profile) and slot == "evening"
            pick = None
            nearby_used = False

            def try_pools(pf: bool) -> None:
                nonlocal pick, nearby_used, used_nearby_fill
                if pick is not None:
                    return
                if pool_local:
                    cand, ok = _pick_from_pool(pool_local, used_norm, prefer_food=pf)
                    if ok and cand:
                        pick = cand
                        return
                if pool_nearby:
                    cand, ok = _pick_from_pool(pool_nearby, used_norm, prefer_food=pf)
                    if ok and cand:
                        pick = cand
                        nearby_used = True
                        used_nearby_fill = True

            try_pools(prefer_food)
            try_pools(not prefer_food)

            if pick:
                pname = str(pick.get("name", "")).strip()
                used_norm.add(_normalize(pname))
                acts_out.append(
                    ItineraryActivity(
                        time_of_day=act.time_of_day,
                        title=_hybrid_title(act.time_of_day, pname),
                        description=_hybrid_description(act.time_of_day, nearby=nearby_used),
                        place_name=pname,
                    )
                )
            else:
                shortage_note = True
                acts_out.append(
                    ItineraryActivity(
                        time_of_day=act.time_of_day,
                        title=act.title,
                        description=act.description,
                        place_name=None,
                    )
                )

        new_days.append(
            ItineraryDay(day_number=day.day_number, theme=day.theme, activities=acts_out)
        )

    notes = list(itinerary.practical_notes)
    if used_nearby_fill:
        note = "Limited matches in selected areas, so nearby popular options were added."
        if note not in notes:
            notes.append(note)
    if shortage_note:
        note2 = (
            "Not enough distinct candidate venues matched every slot uniquely — try widening interests "
            "or neighbourhoods for fuller coverage."
        )
        if note2 not in notes:
            notes.append(note2)

    return TripItinerary(title=itinerary.title, days=new_days, practical_notes=notes)
