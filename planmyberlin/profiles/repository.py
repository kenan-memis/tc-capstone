"""SQLite repository for persisted user profiles."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from planmyberlin.config.loader import get_settings
from planmyberlin.profiles.models import UserProfile, UserProfileUpsert


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _to_json_list(value: list[str]) -> str:
    return json.dumps(value, ensure_ascii=True)


def _from_json_list(value: str) -> list[str]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(x).strip() for x in payload if str(x).strip()]


class UserProfileRepository:
    """CRUD repository with simple schema management."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    party_size_default INTEGER NOT NULL,
                    interest_tags_default TEXT NOT NULL,
                    neighbourhoods_default TEXT NOT NULL,
                    budget_tier_default TEXT NOT NULL,
                    pace_default TEXT NOT NULL,
                    dietary_choice_default TEXT NOT NULL,
                    mobility_choice_default TEXT NOT NULL,
                    include_accommodation_default INTEGER NOT NULL,
                    extra_details_default TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _row_to_model(self, row: sqlite3.Row) -> UserProfile:
        return UserProfile.model_validate(
            {
                "id": str(row["id"]),
                "name": str(row["name"]),
                "party_size_default": int(row["party_size_default"]),
                "interest_tags_default": _from_json_list(str(row["interest_tags_default"])),
                "neighbourhoods_default": _from_json_list(str(row["neighbourhoods_default"])),
                "budget_tier_default": str(row["budget_tier_default"]),
                "pace_default": str(row["pace_default"]),
                "dietary_choice_default": str(row["dietary_choice_default"]),
                "mobility_choice_default": str(row["mobility_choice_default"]),
                "include_accommodation_default": bool(int(row["include_accommodation_default"])),
                "extra_details_default": str(row["extra_details_default"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
        )

    def list_profiles(self) -> list[UserProfile]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM user_profiles ORDER BY updated_at DESC, name ASC"
            ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_profile(self, profile_id: str) -> UserProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
        return self._row_to_model(row) if row else None

    def get_profile_by_name(self, name: str) -> UserProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE name = ?",
                (name,),
            ).fetchone()
        return self._row_to_model(row) if row else None

    def create_profile(self, payload: UserProfileUpsert) -> UserProfile:
        now = _utc_now_iso()
        profile_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_profiles (
                    id, name, party_size_default, interest_tags_default, neighbourhoods_default,
                    budget_tier_default, pace_default, dietary_choice_default, mobility_choice_default,
                    include_accommodation_default, extra_details_default, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    payload.name.strip(),
                    int(payload.party_size_default),
                    _to_json_list(payload.interest_tags_default),
                    _to_json_list(payload.neighbourhoods_default),
                    payload.budget_tier_default,
                    payload.pace_default,
                    payload.dietary_choice_default,
                    payload.mobility_choice_default,
                    1 if payload.include_accommodation_default else 0,
                    payload.extra_details_default,
                    now,
                    now,
                ),
            )
        out = self.get_profile(profile_id)
        if out is None:
            raise RuntimeError("failed to read created profile")
        return out

    def update_profile(self, profile_id: str, payload: UserProfileUpsert) -> UserProfile | None:
        now = _utc_now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE user_profiles
                SET name = ?, party_size_default = ?, interest_tags_default = ?, neighbourhoods_default = ?,
                    budget_tier_default = ?, pace_default = ?, dietary_choice_default = ?, mobility_choice_default = ?,
                    include_accommodation_default = ?, extra_details_default = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.name.strip(),
                    int(payload.party_size_default),
                    _to_json_list(payload.interest_tags_default),
                    _to_json_list(payload.neighbourhoods_default),
                    payload.budget_tier_default,
                    payload.pace_default,
                    payload.dietary_choice_default,
                    payload.mobility_choice_default,
                    1 if payload.include_accommodation_default else 0,
                    payload.extra_details_default,
                    now,
                    profile_id,
                ),
            )
            if cur.rowcount == 0:
                return None
        return self.get_profile(profile_id)

    def delete_profile(self, profile_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM user_profiles WHERE id = ?", (profile_id,))
            return cur.rowcount > 0


def build_user_profile_repository() -> UserProfileRepository:
    """Factory using settings path, with schema initialized."""
    cfg = get_settings().get("profiles", {})
    db_path = Path(str(cfg.get("sqlite_path", "data/app/profiles.db")))
    repo = UserProfileRepository(db_path)
    repo.init_schema()
    return repo
