from planmyberlin.models.trip_profile import TripProfile
from planmyberlin.rag import retrieve_seed_context


def _profile(**kwargs: object) -> TripProfile:
    base = {
        "days": 2,
        "party_size": 2,
        "interest_tags": ["Museums & galleries", "Food & dining"],
        "neighbourhoods": ["Alexanderplatz & Mitte core"],
        "budget_tier": "moderate",
        "pace": "balanced",
        "dietary_choice": "Doesn't matter / no preference",
        "mobility_choice": "No specific needs",
        "include_accommodation": True,
        "extra_details": "",
    }
    base.update(kwargs)
    return TripProfile.model_validate(base)


def test_retrieve_seed_context_returns_ranked_items() -> None:
    payload = retrieve_seed_context(_profile(), limit=6)
    items = payload["items"]
    assert items, "expected at least one retrieved seed record"
    assert len(items) <= 6
    assert all("name" in it and "summary" in it for it in items)


def test_retrieve_seed_prefers_selected_district() -> None:
    payload = retrieve_seed_context(
        _profile(neighbourhoods=["Kreuzberg"], interest_tags=["Food & dining"]),
        limit=5,
    )
    districts = [str(it.get("district", "")).lower() for it in payload["items"]]
    assert any("kreuzberg" in d for d in districts)
