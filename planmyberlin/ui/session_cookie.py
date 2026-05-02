"""Opaque session token in a browser cookie; validation stays server-side (SQLite)."""

from __future__ import annotations

import datetime
import os

import streamlit as st
from extra_streamlit_components import CookieManager

SESSION_COOKIE_NAME = "planmyberlin_session"
_COOKIE_COMPONENT_KEY = "planmyberlin_cookie_component_v1"


def cookie_secure_flag() -> bool:
    """Use Secure cookies on HTTPS (e.g. Cloud Run). Disable for plain http://localhost."""
    return os.getenv("COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes")


def _manager() -> CookieManager:
    if _COOKIE_COMPONENT_KEY not in st.session_state:
        st.session_state[_COOKIE_COMPONENT_KEY] = CookieManager(key=_COOKIE_COMPONENT_KEY)
    return st.session_state[_COOKIE_COMPONENT_KEY]


def read_session_token_from_cookie() -> str:
    cm = _manager()
    cm.get_all(key=f"{_COOKIE_COMPONENT_KEY}_read")
    raw = cm.get(SESSION_COOKIE_NAME)
    return str(raw or "").strip()


def set_session_token_cookie(token: str) -> None:
    if not (token or "").strip():
        return
    cm = _manager()
    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)
    cm.set(
        SESSION_COOKIE_NAME,
        token.strip(),
        key=f"{_COOKIE_COMPONENT_KEY}_set",
        path="/",
        expires_at=expires,
        max_age=30.0 * 24 * 3600,
        secure=cookie_secure_flag(),
        same_site="lax",
    )


def clear_session_token_cookie() -> None:
    cm = _manager()
    try:
        cm.delete(SESSION_COOKIE_NAME, key=f"{_COOKIE_COMPONENT_KEY}_del")
    except KeyError:
        pass
