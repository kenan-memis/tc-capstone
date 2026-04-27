"""Tests for unique venue assignment and flexible slot budgeting."""

from planmyberlin.itinerary.models import ItineraryActivity, ItineraryDay, TripItinerary
from planmyberlin.itinerary.place_policy import (
    apply_unique_place_policy,
    flexible_slot_budget,
    merge_retrieval_candidates,
)


def test_merge_retrieval_candidates_dedupes_by_name() -> None:
    merged = merge_retrieval_candidates(
        {
            "enriched_items": [{"name": "A", "district": "Mitte"}],
            "retrieved_items": [{"name": "A", "district": "Mitte"}, {"name": "B", "district": "X"}],
        }
    )
    assert [x["name"] for x in merged[:2]] == ["A", "B"]
    assert len(merged) >= 2


def test_flexible_slot_budget() -> None:
    assert flexible_slot_budget(1) == 0
    assert flexible_slot_budget(2) == 0
    assert flexible_slot_budget(3) == 1
    assert flexible_slot_budget(4) == 2


def test_apply_unique_place_three_days_one_flexible_afternoon_day3() -> None:
    names = [f"V{i}" for i in range(12)]
    candidates = [{"name": n, "category": "places", "district": "Mitte"} for n in names]
    itinerary = TripItinerary(
        title="t",
        days=[
            ItineraryDay(
                day_number=i,
                theme=f"D{i}",
                activities=[
                    ItineraryActivity(time_of_day=s, title="x", description="y", place_name=None)
                    for s in ("morning", "afternoon", "evening")
                ],
            )
            for i in range(1, 4)
        ],
    )
    profile: dict = {"days": 3, "interest_tags": [], "neighbourhoods": []}
    out = apply_unique_place_policy(itinerary, profile=profile, candidates=candidates)

    places = [
        a.place_name for d in out.days for a in d.activities if str(a.place_name or "").strip()
    ]
    assert len(places) == len(set(places))

    none_slots = [
        (d.day_number, str(a.time_of_day).lower())
        for d in out.days
        for a in d.activities
        if not a.place_name
    ]
    assert none_slots == [(3, "afternoon")]


def test_apply_unique_place_reuses_when_pool_smaller_than_slots() -> None:
    """Shortlists shorter than slot count still get filled (least-used repeats), no Place: None."""
    names = [f"V{i}" for i in range(4)]
    candidates = [{"name": n, "category": "places", "district": "Mitte"} for n in names]
    itinerary = TripItinerary(
        title="t",
        days=[
            ItineraryDay(
                day_number=i,
                theme=f"D{i}",
                activities=[
                    ItineraryActivity(time_of_day=s, title="x", description="y", place_name=None)
                    for s in ("morning", "afternoon", "evening")
                ],
            )
            for i in range(1, 3)
        ],
    )
    profile: dict = {"days": 2, "interest_tags": [], "neighbourhoods": []}
    out = apply_unique_place_policy(itinerary, profile=profile, candidates=candidates)
    filled = [
        bool(str(a.place_name or "").strip()) for d in out.days for a in d.activities
    ]
    assert all(filled)
    notes_blob = " ".join(out.practical_notes).lower()
    assert "reused" in notes_blob


def test_apply_unique_place_two_days_all_named_when_pool_large() -> None:
    names = [f"P{i}" for i in range(8)]
    candidates = [{"name": n, "category": "places"} for n in names]
    itinerary = TripItinerary(
        title="t",
        days=[
            ItineraryDay(
                day_number=i,
                theme=f"D{i}",
                activities=[
                    ItineraryActivity(time_of_day=s, title="x", description="y", place_name=None)
                    for s in ("morning", "afternoon", "evening")
                ],
            )
            for i in range(1, 3)
        ],
    )
    profile: dict = {"days": 2, "interest_tags": [], "neighbourhoods": []}
    out = apply_unique_place_policy(itinerary, profile=profile, candidates=candidates)
    assert all(a.place_name for d in out.days for a in d.activities)


def test_merge_candidates_citywide_fallback_supports_empty_sources() -> None:
    merged = merge_retrieval_candidates({"enriched_items": [], "retrieved_items": []})
    assert len(merged) >= 6
    assert all(str(x.get("name", "")).strip() for x in merged[:6])
