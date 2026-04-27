"""Unique venue assignment and flexible (non-venue) slots for multi-day itineraries."""

from __future__ import annotations

from typing import Any

from planmyberlin.itinerary.grounding import candidate_name_allowlist
from planmyberlin.itinerary.models import ItineraryActivity, ItineraryDay, TripItinerary


_CITYWIDE_DEFAULT_CANDIDATES: list[dict[str, str]] = [
    {"name": "Brandenburg Gate", "category": "places", "district": "Mitte"},
    {"name": "Museum Island", "category": "places", "district": "Mitte"},
    {"name": "Berlin Cathedral", "category": "places", "district": "Mitte"},
    {"name": "East Side Gallery", "category": "places", "district": "Friedrichshain"},
    {"name": "Tiergarten", "category": "places", "district": "Tiergarten"},
    {"name": "Tempelhofer Feld", "category": "places", "district": "Tempelhof"},
    {"name": "Charlottenburg Palace", "category": "places", "district": "Charlottenburg"},
    {"name": "Hackescher Markt", "category": "places", "district": "Mitte"},
    {"name": "Burgermeister", "category": "food", "district": "Kreuzberg"},
    {"name": "Mustafa's Gemuse Kebap", "category": "food", "district": "Kreuzberg"},
    {"name": "Five Elephant", "category": "food", "district": "Kreuzberg"},
    {"name": "Cafe am Neuen See", "category": "food", "district": "Tiergarten"},
]


def _is_poor_display_name(raw: str) -> bool:
    """True for quirky question-style or sentence-like venue names that read badly as a 'Place' label."""
    name = (raw or "").strip()
    if not name:
        return True
    lower = name.lower()
    if "?" in name:
        return True
    if lower.startswith(("what ", "why ", "how ", "when ", "where ", "who ")):
        return True
    wc = len(name.split())
    if wc >= 10:
        return True
    return False


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
    # Keep itinerary generation robust even when retrieval APIs are sparse for selected districts.
    # These are only used as a citywide backup pool after local district candidates are consumed.
    if len(merged) < 12:
        for item in _CITYWIDE_DEFAULT_CANDIDATES:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            k = name.lower()
            if k in seen:
                continue
            seen.add(k)
            merged.append(dict(item))
            if len(merged) >= 12:
                break
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
        return f"Evening at {place_name}"
    return f"Explore {place_name}"


def _hybrid_description(
    slot: str,
    place_name: str,
    *,
    nearby: bool,
    reused: bool,
) -> str:
    pn = (place_name or "").strip()
    if nearby:
        return "Your selected districts had limited matches, so this popular Berlin option was added."
    if reused and pn:
        return (
            f"Another stop at {pn} — useful when the shortlist cannot cover every slot with a new name."
        )
    s = (slot or "").strip().lower()
    if s == "morning":
        return f"Start the day at {pn} with a focused visit and easy pacing."
    if s == "afternoon":
        return f"Spend the afternoon around {pn}; adjust pacing to energy and weather."
    if s == "evening":
        return (
            f"Wind down at {pn} — plan for dinner or drinks that fit your group and dietary preference."
        )
    return f"Flexible time around {pn}, aligned with your selected areas."


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
    allow_poor_names: bool,
) -> tuple[dict[str, Any] | None, bool]:
    """Pick one unused item from pool (removed in-place). Prefer food venues when prefer_food is True."""
    eligible = [
        i
        for i, it in enumerate(pool)
        if _normalize(str(it.get("name", ""))) not in used_norm
        and (allow_poor_names or not _is_poor_display_name(str(it.get("name", ""))))
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


def _prefer_slot_score(item: dict[str, Any], prefer_food: bool) -> int:
    """Higher = better fit for this time-of-day preference."""
    f = _is_foodish(item)
    if prefer_food:
        return 2 if f else 0
    return 2 if not f else 0


def _pick_reuse_least_used(
    master: list[dict[str, Any]],
    use_counts: dict[str, int],
    *,
    prefer_food: bool,
    allow_poor_names: bool,
) -> tuple[dict[str, Any] | None, bool]:
    """
    When unique names are exhausted, pick again from the full shortlist (repeats allowed).
    Chooses the least-used venue so repeats are spread out; avoids poor display names when possible.
    """
    pool = master
    if not allow_poor_names:
        good = [m for m in master if not _is_poor_display_name(str(m.get("name", "")))]
        if good:
            pool = good

    best: dict[str, Any] | None = None
    best_key: tuple[int, int, str] | None = None
    for it in pool:
        name = str(it.get("name", "")).strip()
        if not name:
            continue
        nk = _normalize(name)
        uses = use_counts.get(nk, 0)
        ps = _prefer_slot_score(it, prefer_food)
        key = (uses, -ps, nk)
        if best_key is None or key < best_key:
            best_key = key
            best = it
    return (best, True) if best else (None, False)


def apply_unique_place_policy(
    itinerary: TripItinerary,
    *,
    profile: dict[str, Any],
    candidates: list[dict[str, Any]],
    weather_bias: str = "",
) -> TripItinerary:
    """
    Prefer trip-wide distinct venues; optional flexible non-venue afternoons on longer trips.
    When the shortlist is shorter than named slots, repeats least-used venues (spread out) rather than
    leaving Place empty. Skips awkward sentence-like venue labels when alternatives exist.
    """
    days = len(itinerary.days)
    budget = flexible_slot_budget(days)
    flex_coords = _flex_positions(days, budget)

    selected = [str(x).strip().lower() for x in profile.get("neighbourhoods", []) if str(x).strip()]
    allowed_norm, norm_to_canonical = candidate_name_allowlist(candidates)

    all_ordered: list[dict[str, Any]] = []
    seen_build: set[str] = set()
    for item in candidates:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        k = name.lower()
        if k in seen_build:
            continue
        seen_build.add(k)
        all_ordered.append(dict(item))

    local: list[dict[str, Any]] = []
    nearby: list[dict[str, Any]] = []
    for item in all_ordered:
        if _is_local_candidate(item, selected):
            local.append(dict(item))
        else:
            nearby.append(dict(item))

    pool_local = list(local)
    pool_nearby = list(nearby)
    used_norm: set[str] = set()
    use_counts: dict[str, int] = {}
    used_nearby_fill = False
    shortage_note = False
    reuse_note = False

    flex_counter = 0
    new_days: list[ItineraryDay] = []

    def _record_assignment(norm_key: str) -> bool:
        """Register use of a venue; returns True if this name was already used earlier in the trip."""
        before = use_counts.get(norm_key, 0)
        use_counts[norm_key] = before + 1
        used_norm.add(norm_key)
        return before > 0

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
            if canon and not _is_poor_display_name(canon):
                nk = _normalize(canon)
                if nk not in used_norm:
                    _record_assignment(nk)
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

            def try_pools(pf: bool, *, allow_bad: bool) -> None:
                nonlocal pick, nearby_used, used_nearby_fill
                if pick is not None:
                    return
                if pool_local:
                    cand, ok = _pick_from_pool(
                        pool_local,
                        used_norm,
                        prefer_food=pf,
                        allow_poor_names=allow_bad,
                    )
                    if ok and cand:
                        pick = cand
                        return
                if pool_nearby:
                    cand, ok = _pick_from_pool(
                        pool_nearby,
                        used_norm,
                        prefer_food=pf,
                        allow_poor_names=allow_bad,
                    )
                    if ok and cand:
                        pick = cand
                        nearby_used = True
                        used_nearby_fill = True

            try_pools(prefer_food, allow_bad=False)
            try_pools(not prefer_food, allow_bad=False)
            try_pools(prefer_food, allow_bad=True)
            try_pools(not prefer_food, allow_bad=True)

            if pick:
                pname = str(pick.get("name", "")).strip()
                nk = _normalize(pname)
                reused = _record_assignment(nk)
                if reused:
                    reuse_note = True
                acts_out.append(
                    ItineraryActivity(
                        time_of_day=act.time_of_day,
                        title=_hybrid_title(act.time_of_day, pname),
                        description=_hybrid_description(
                            act.time_of_day,
                            pname,
                            nearby=nearby_used,
                            reused=reused,
                        ),
                        place_name=pname,
                    )
                )
                continue

            reuse_pick = None
            ru_nearby = False
            rp, ok = _pick_reuse_least_used(
                all_ordered,
                use_counts,
                prefer_food=prefer_food,
                allow_poor_names=False,
            )
            if ok and rp:
                reuse_pick = rp
                ru_nearby = not _is_local_candidate(rp, selected)
            if reuse_pick is None:
                rp2, ok2 = _pick_reuse_least_used(
                    all_ordered,
                    use_counts,
                    prefer_food=prefer_food,
                    allow_poor_names=True,
                )
                if ok2 and rp2:
                    reuse_pick = rp2
                    ru_nearby = not _is_local_candidate(rp2, selected)
            if reuse_pick is None:
                rp3, ok3 = _pick_reuse_least_used(
                    all_ordered,
                    use_counts,
                    prefer_food=not prefer_food,
                    allow_poor_names=False,
                )
                if ok3 and rp3:
                    reuse_pick = rp3
                    ru_nearby = not _is_local_candidate(rp3, selected)
            if reuse_pick is None:
                rp4, ok4 = _pick_reuse_least_used(
                    all_ordered,
                    use_counts,
                    prefer_food=not prefer_food,
                    allow_poor_names=True,
                )
                if ok4 and rp4:
                    reuse_pick = rp4
                    ru_nearby = not _is_local_candidate(rp4, selected)

            if reuse_pick:
                pname = str(reuse_pick.get("name", "")).strip()
                nk = _normalize(pname)
                reused = _record_assignment(nk)
                if reused:
                    reuse_note = True
                if ru_nearby:
                    used_nearby_fill = True
                acts_out.append(
                    ItineraryActivity(
                        time_of_day=act.time_of_day,
                        title=_hybrid_title(act.time_of_day, pname),
                        description=_hybrid_description(
                            act.time_of_day,
                            pname,
                            nearby=ru_nearby,
                            reused=reused,
                        ),
                        place_name=pname,
                    )
                )
                continue

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
        note = "Your selected districts had limited matches, so popular options from other parts of Berlin were added."
        if note not in notes:
            notes.append(note)
    if reuse_note:
        note_r = (
            "Some places were reused because available unique matches were not enough for every named time slot."
        )
        if note_r not in notes:
            notes.append(note_r)
    if shortage_note:
        note2 = (
            "We could not find enough place matches for every slot. Try broader interests or districts."
        )
        if note2 not in notes:
            notes.append(note2)

    return TripItinerary(title=itinerary.title, days=new_days, practical_notes=notes)
