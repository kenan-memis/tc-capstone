import pytest

from planmyberlin.models.trip_profile import TripProfile
from planmyberlin.rag import router


def _profile() -> TripProfile:
    return TripProfile.model_validate(
        {
            "days": 2,
            "party_size": 2,
            "interest_tags": ["Food & dining"],
            "neighbourhoods": ["Kreuzberg"],
            "budget_tier": "moderate",
            "pace": "balanced",
            "dietary_choice": "Doesn't matter / no preference",
            "mobility_choice": "No specific needs",
            "include_accommodation": True,
            "extra_details": "",
        }
    )


def test_router_seed_backend_direct() -> None:
    payload = router.retrieve_context(_profile(), retrieval_cfg={"backend": "seed", "seed_limit": 4})
    assert payload["backend"] == "seed"
    assert len(payload["items"]) <= 4


def test_router_auto_fallback_when_chroma_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "chroma_index_ready", lambda **_: False)
    payload = router.retrieve_context(_profile(), retrieval_cfg={"backend": "auto", "seed_limit": 3})
    assert payload["backend"] == "seed"


def test_router_chroma_backend_raises_if_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "chroma_index_ready", lambda **_: False)
    with pytest.raises(Exception):
        router.retrieve_context(_profile(), retrieval_cfg={"backend": "chroma", "seed_limit": 3})


def test_router_strict_area_filter_keeps_selected_borough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        router,
        "retrieve_seed_context",
        lambda *_args, **_kwargs: {
            "items": [
                {"name": "A", "category": "places", "district": "Kreuzberg", "source_file": "x"},
                {"name": "B", "category": "places", "district": "Mitte (overall)", "source_file": "y"},
            ],
            "citations": [],
        },
    )
    payload = router.retrieve_context(
        _profile(),
        retrieval_cfg={"backend": "seed", "seed_limit": 8, "strict_area_filter": True, "nearby_fallback": False},
    )
    assert payload["retrieval_mode"] == "strict"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["district"] == "Kreuzberg"


def test_router_nearby_fallback_when_strict_insufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        router,
        "retrieve_seed_context",
        lambda *_args, **_kwargs: {
            "items": [
                {"name": "A", "category": "places", "district": "Kreuzberg", "source_file": "x"},
                {"name": "B", "category": "places", "district": "Mitte (overall)", "source_file": "y"},
                {"name": "C", "category": "places", "district": "Friedrichshain", "source_file": "z"},
            ],
            "citations": [],
        },
    )
    payload = router.retrieve_context(
        _profile(),
        retrieval_cfg={
            "backend": "seed",
            "seed_limit": 8,
            "strict_area_filter": True,
            "strict_min_items": 3,
            "nearby_fallback": True,
        },
    )
    assert payload["retrieval_mode"] == "nearby_fallback"
    assert len(payload["items"]) >= 2


def test_router_food_interest_guarantee_injects_food_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        router,
        "retrieve_seed_context",
        lambda *_args, **_kwargs: {
            "items": [
                {"name": "Museum A", "category": "places", "district": "Kreuzberg", "source_file": "x", "tags": ["museum"]},
                {"name": "Museum B", "category": "places", "district": "Kreuzberg", "source_file": "x", "tags": ["art"]},
                {"name": "Cafe C", "category": "restaurants", "district": "Kreuzberg", "source_file": "x", "tags": ["cafe"]},
            ],
            "citations": [],
        },
    )
    payload = router.retrieve_context(
        _profile(),
        retrieval_cfg={
            "backend": "seed",
            "seed_limit": 2,
            "strict_area_filter": True,
            "nearby_fallback": False,
            "food_interest_guarantee": True,
            "food_interest_min_items": 1,
        },
    )
    assert any("restaurant" in str(x.get("category", "")) for x in payload["items"])


def test_router_uses_wider_candidate_pool_for_food_interests(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def _fake_seed(_profile, *, limit: int):  # noqa: ANN001
        calls.append(limit)
        return {"items": [], "citations": []}

    monkeypatch.setattr(router, "retrieve_seed_context", _fake_seed)
    payload = router.retrieve_context(
        _profile(),
        retrieval_cfg={"backend": "seed", "seed_limit": 8, "food_interest_guarantee": True},
    )
    assert payload["backend"] == "seed"
    assert calls and calls[0] >= 24
