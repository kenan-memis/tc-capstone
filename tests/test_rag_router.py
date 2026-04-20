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
