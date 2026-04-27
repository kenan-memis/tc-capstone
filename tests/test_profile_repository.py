from pathlib import Path

import pytest

from planmyberlin.profiles import AppUserUpsert, UserProfileRepository, UserProfileUpsert


def _repo(tmp_path: Path) -> UserProfileRepository:
    repo = UserProfileRepository(tmp_path / "profiles.db")
    repo.init_schema()
    return repo


def _user(repo: UserProfileRepository, name: str = "User A") -> str:
    return repo.create_user(AppUserUpsert(username=name)).id


def test_create_and_get_profile(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    user_id = _user(repo, "Kenan User")
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
        ),
        user_id=user_id,
    )
    loaded = repo.get_profile(created.id, user_id=user_id)
    assert loaded is not None
    assert loaded.name == "Kenan"
    assert loaded.interest_tags_default == ["Museums & galleries"]
    assert loaded.user_id == user_id


def test_update_profile(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    user_id = _user(repo, "Updater")
    created = repo.create_profile(
        UserProfileUpsert(
            name="Profile A",
            pace_default="balanced",
            budget_tier_default="moderate",
            dietary_choice_default="Doesn't matter / no preference",
            mobility_choice_default="No specific needs",
        ),
        user_id=user_id,
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
        user_id=user_id,
    )
    assert updated is not None
    assert updated.name == "Profile A Updated"
    assert updated.pace_default == "relaxed"
    assert updated.include_accommodation_default is False


def test_list_and_delete_profile(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    user_id = _user(repo, "Lister")
    p1 = repo.create_profile(
        UserProfileUpsert(
            name="One",
            pace_default="balanced",
            budget_tier_default="moderate",
            dietary_choice_default="Doesn't matter / no preference",
            mobility_choice_default="No specific needs",
        ),
        user_id=user_id,
    )
    repo.create_profile(
        UserProfileUpsert(
            name="Two",
            pace_default="relaxed",
            budget_tier_default="low",
            dietary_choice_default="Doesn't matter / no preference",
            mobility_choice_default="No specific needs",
        ),
        user_id=user_id,
    )
    listed = repo.list_profiles(user_id=user_id)
    assert len(listed) == 2
    assert repo.delete_profile(p1.id, user_id=user_id) is True
    assert repo.get_profile(p1.id, user_id=user_id) is None


def test_profile_name_is_unique(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    user_a = _user(repo, "User A")
    user_b = _user(repo, "User B")
    repo.create_profile(
        UserProfileUpsert(
            name="Unique Name",
            pace_default="balanced",
            budget_tier_default="moderate",
            dietary_choice_default="Doesn't matter / no preference",
            mobility_choice_default="No specific needs",
        ),
        user_id=user_a,
    )
    repo.create_profile(
        UserProfileUpsert(
            name="Unique Name",
            pace_default="balanced",
            budget_tier_default="moderate",
            dietary_choice_default="Doesn't matter / no preference",
            mobility_choice_default="No specific needs",
        ),
        user_id=user_b,
    )
    with pytest.raises(Exception):
        repo.create_profile(
            UserProfileUpsert(
                name="Unique Name",
                pace_default="balanced",
                budget_tier_default="moderate",
                dietary_choice_default="Doesn't matter / no preference",
                mobility_choice_default="No specific needs",
            ),
            user_id=user_a,
        )


def test_user_crud(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    u = repo.create_user(AppUserUpsert(username="Demo User"))
    assert repo.get_user(u.id) is not None
    assert repo.get_user_by_name("Demo User") is not None
    assert len(repo.list_users()) == 1


def test_authenticate_user_with_hashed_password(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    created = repo.create_user_with_password(username="auth-user", password="StrongPass123")
    ok = repo.authenticate_user(username="auth-user", password="StrongPass123")
    bad = repo.authenticate_user(username="auth-user", password="wrong-pass")
    assert ok is not None
    assert ok.id == created.id
    assert bad is None


def test_session_create_and_resolve_user(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    user = repo.create_user_with_password(username="session-user", password="StrongPass123")
    token = repo.create_session(user_id=user.id, ttl_days=1)
    resolved = repo.get_user_by_session(token=token)
    assert resolved is not None
    assert resolved.id == user.id
    repo.revoke_session(token=token)
    assert repo.get_user_by_session(token=token) is None


def test_create_user_with_duplicate_username_raises_value_error(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.create_user_with_password(username="same-user", password="StrongPass123")
    with pytest.raises(ValueError):
        repo.create_user_with_password(username="same-user", password="StrongPass123")
