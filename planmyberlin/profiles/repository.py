"""SQLite repository for persisted user profiles."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from planmyberlin.config.loader import get_settings
from planmyberlin.profiles.models import AppUser, AppUserUpsert, UserProfile, UserProfileUpsert


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
                CREATE TABLE IF NOT EXISTS app_users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    onboarding_completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
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
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES app_users(id)
                )
                """
            )
            cols = {
                str(r["name"])
                for r in conn.execute("PRAGMA table_info(user_profiles)").fetchall()
                if isinstance(r, sqlite3.Row)
            }
            if "user_id" not in cols:
                conn.execute("ALTER TABLE user_profiles ADD COLUMN user_id TEXT NOT NULL DEFAULT 'legacy-user'")
            user_cols = {
                str(r["name"])
                for r in conn.execute("PRAGMA table_info(app_users)").fetchall()
                if isinstance(r, sqlite3.Row)
            }
            if "display_name" in user_cols and "username" not in user_cols:
                conn.execute("ALTER TABLE app_users ADD COLUMN username TEXT")
                conn.execute("UPDATE app_users SET username = display_name WHERE username IS NULL OR username = ''")
            if "password_salt" not in user_cols:
                conn.execute("ALTER TABLE app_users ADD COLUMN password_salt TEXT")
            if "password_hash" not in user_cols:
                conn.execute("ALTER TABLE app_users ADD COLUMN password_hash TEXT")
            if "onboarding_completed" not in user_cols:
                conn.execute("ALTER TABLE app_users ADD COLUMN onboarding_completed INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE app_users SET password_salt = '' WHERE password_salt IS NULL")
            conn.execute("UPDATE app_users SET password_hash = '' WHERE password_hash IS NULL")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_app_users_username ON app_users(username)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_profiles_user ON user_profiles(user_id)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_profiles_user_name ON user_profiles(user_id, name)")

    def _row_to_user(self, row: sqlite3.Row) -> AppUser:
        return AppUser.model_validate(
            {
                "id": str(row["id"]),
                "username": str(row["username"]),
                "onboarding_completed": bool(int(row["onboarding_completed"])),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
        )

    def _hash_password(self, password: str, *, salt_hex: str) -> str:
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 120_000)
        return dk.hex()

    def _row_to_model(self, row: sqlite3.Row) -> UserProfile:
        return UserProfile.model_validate(
            {
                "id": str(row["id"]),
                "user_id": str(row["user_id"]),
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

    def list_users(self) -> list[AppUser]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM app_users ORDER BY updated_at DESC, username ASC"
            ).fetchall()
        return [self._row_to_user(r) for r in rows]

    def get_user(self, user_id: str) -> AppUser | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM app_users WHERE id = ?", (user_id,)).fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_name(self, display_name: str) -> AppUser | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM app_users WHERE username = ?",
                (display_name.strip(),),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def create_user(self, payload: AppUserUpsert) -> AppUser:
        now = _utc_now_iso()
        user_id = str(uuid.uuid4())
        salt_hex = os.urandom(16).hex()
        placeholder_hash = self._hash_password("temporary-password", salt_hex=salt_hex)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO app_users (id, username, password_salt, password_hash, onboarding_completed, created_at, updated_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
                (user_id, payload.username.strip(), salt_hex, placeholder_hash, now, now),
            )
        out = self.get_user(user_id)
        if out is None:
            raise RuntimeError("failed to read created user")
        return out

    def create_user_with_password(self, *, username: str, password: str) -> AppUser:
        username = username.strip()
        if len(username) < 3:
            raise ValueError("username must be at least 3 characters")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        if self.get_user_by_name(username) is not None:
            raise ValueError("username already exists")
        now = _utc_now_iso()
        user_id = str(uuid.uuid4())
        salt_hex = os.urandom(16).hex()
        hashed = self._hash_password(password, salt_hex=salt_hex)
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO app_users (id, username, password_salt, password_hash, onboarding_completed, created_at, updated_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
                    (user_id, username, salt_hex, hashed, now, now),
                )
        except sqlite3.IntegrityError as exc:
            msg = str(exc).lower()
            if "username" in msg or "unique" in msg:
                raise ValueError("username already exists") from exc
            raise
        out = self.get_user(user_id)
        if out is None:
            raise RuntimeError("failed to read created user")
        return out

    def authenticate_user(self, *, username: str, password: str) -> AppUser | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM app_users WHERE username = ?",
                (username.strip(),),
            ).fetchone()
        if not row:
            return None
        salt_hex = str(row["password_salt"] or "")
        expected_hash = str(row["password_hash"] or "")
        if not salt_hex or not expected_hash:
            return None
        got = self._hash_password(password, salt_hex=salt_hex)
        if got != expected_hash:
            return None
        return self._row_to_user(row)

    def set_onboarding_completed(self, *, user_id: str, completed: bool) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE app_users SET onboarding_completed = ?, updated_at = ? WHERE id = ?",
                (1 if completed else 0, now, user_id),
            )

    def list_profiles(self, *, user_id: str) -> list[UserProfile]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM user_profiles WHERE user_id = ? ORDER BY updated_at DESC, name ASC",
                (user_id,),
            ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_profile(self, profile_id: str, *, user_id: str) -> UserProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE id = ? AND user_id = ?",
                (profile_id, user_id),
            ).fetchone()
        return self._row_to_model(row) if row else None

    def get_profile_by_name(self, name: str, *, user_id: str) -> UserProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE name = ? AND user_id = ?",
                (name, user_id),
            ).fetchone()
        return self._row_to_model(row) if row else None

    def create_profile(self, payload: UserProfileUpsert, *, user_id: str) -> UserProfile:
        now = _utc_now_iso()
        profile_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_profiles (
                    id, user_id, name, party_size_default, interest_tags_default, neighbourhoods_default,
                    budget_tier_default, pace_default, dietary_choice_default, mobility_choice_default,
                    include_accommodation_default, extra_details_default, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    user_id,
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
        out = self.get_profile(profile_id, user_id=user_id)
        if out is None:
            raise RuntimeError("failed to read created profile")
        return out

    def update_profile(self, profile_id: str, payload: UserProfileUpsert, *, user_id: str) -> UserProfile | None:
        now = _utc_now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE user_profiles
                SET name = ?, party_size_default = ?, interest_tags_default = ?, neighbourhoods_default = ?,
                    budget_tier_default = ?, pace_default = ?, dietary_choice_default = ?, mobility_choice_default = ?,
                    include_accommodation_default = ?, extra_details_default = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
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
                    user_id,
                ),
            )
            if cur.rowcount == 0:
                return None
        return self.get_profile(profile_id, user_id=user_id)

    def delete_profile(self, profile_id: str, *, user_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM user_profiles WHERE id = ? AND user_id = ?", (profile_id, user_id))
            return cur.rowcount > 0


def build_user_profile_repository() -> UserProfileRepository:
    """Factory using settings path, with schema initialized."""
    cfg = get_settings().get("profiles", {})
    db_path = Path(str(cfg.get("sqlite_path", "data/app/profiles.db")))
    repo = UserProfileRepository(db_path)
    repo.init_schema()
    return repo
