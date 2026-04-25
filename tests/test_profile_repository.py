from pathlib import Path

import pytest

from planmyberlin.profiles import UserProfileRepository, UserProfileUpsert


def _repo(tmp_path: Path) -> UserProfileRepository:
    repo = UserProfileRepository(tmp_path / "profiles.db")
    repo.init_schema()
    return repo


def test_create_and_get_profile(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    created = repo.create_profile(
        UserProfileUpsert(
            name="Kenan",
            pace_default="balanced",
            budget_tier_default="moderate",
            dietary_choice_default="Doesn't matter / no preference",
            mobility_choice_default="No specific needs",
            interest_tags_default=["Museums & galleries"],
            neighbourhoods_default=["Alexanderplatz & Mitte core"],
            include_accommodation_default=True,
        )
    )
    loaded = repo.get_profile(created.id)
    assert loaded is not None
    assert loaded.name == "Kenan"
    assert loaded.interest_tags_default == ["Museums & galleries"]


def test_update_profile(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    created = repo.create_profile(
        UserProfileUpsert(
            name="Profile A",
            pace_default="balanced",
            budget_tier_default="moderate",
            dietary_choice_default="Doesn't matter / no preference",
            mobility_choice_default="No specific needs",
        )
    )
    updated = repo.update_profile(
        created.id,
        UserProfileUpsert(
            name="Profile A Updated",
            pace_default="relaxed",
            budget_tier_default="high",
            dietary_choice_default="Doesn't matter / no preference",
            mobility_choice_default="No specific needs",
            include_accommodation_default=False,
        ),
    )
    assert updated is not None
    assert updated.name == "Profile A Updated"
    assert updated.pace_default == "relaxed"
    assert updated.include_accommodation_default is False


def test_list_and_delete_profile(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    p1 = repo.create_profile(
        UserProfileUpsert(
            name="One",
            pace_default="balanced",
            budget_tier_default="moderate",
            dietary_choice_default="Doesn't matter / no preference",
            mobility_choice_default="No specific needs",
        )
    )
    repo.create_profile(
        UserProfileUpsert(
            name="Two",
            pace_default="relaxed",
            budget_tier_default="low",
            dietary_choice_default="Doesn't matter / no preference",
            mobility_choice_default="No specific needs",
        )
    )
    listed = repo.list_profiles()
    assert len(listed) == 2
    assert repo.delete_profile(p1.id) is True
    assert repo.get_profile(p1.id) is None


def test_profile_name_is_unique(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.create_profile(
        UserProfileUpsert(
            name="Unique Name",
            pace_default="balanced",
            budget_tier_default="moderate",
            dietary_choice_default="Doesn't matter / no preference",
            mobility_choice_default="No specific needs",
        )
    )
    with pytest.raises(Exception):
        repo.create_profile(
            UserProfileUpsert(
                name="Unique Name",
                pace_default="balanced",
                budget_tier_default="moderate",
                dietary_choice_default="Doesn't matter / no preference",
                mobility_choice_default="No specific needs",
            )
        )
