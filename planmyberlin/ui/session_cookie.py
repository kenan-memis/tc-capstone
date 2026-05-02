"""Opaque session token in a browser cookie; validation stays server-side (SQLite)."""

from __future__ import annotations

import datetime
import os
from typing import Any

import streamlit as st
from extra_streamlit_components import CookieManager

from planmyberlin.observability import get_logger

SESSION_COOKIE_NAME = "planmyberlin_session"
_COOKIE_COMPONENT_KEY = "planmyberlin_cookie_component_v1"

_log = get_logger(__name__)


def cookie_secure_flag() -> bool:
    """Use Secure cookies on HTTPS (e.g. Cloud Run). Disable for plain http://localhost."""
    return os.getenv("COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes")


def _manager() -> Any | None:
    """CookieManager can fail on some Streamlit runs (component lifecycle); treat as optional."""
    try:
        if _COOKIE_COMPONENT_KEY not in st.session_state:
            st.session_state[_COOKIE_COMPONENT_KEY] = CookieManager(key=_COOKIE_COMPONENT_KEY)
        return st.session_state[_COOKIE_COMPONENT_KEY]
    except Exception as exc:
        _log.warning("Cookie manager unavailable: %s", exc)
        return None


def read_session_token_from_cookie() -> str:
    try:
        cm = _manager()
        if cm is None:
            return ""
        cm.get_all(key=f"{_COOKIE_COMPONENT_KEY}_read")
        raw = cm.get(SESSION_COOKIE_NAME)
        return str(raw or "").strip()
    except Exception as exc:
        _log.warning("Could not read session cookie: %s", exc)
        return ""


def set_session_token_cookie(token: str) -> None:
    if not (token or "").strip():
        return
    try:
        cm = _manager()
        if cm is None:
            return
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
    except Exception as exc:
        _log.warning("Could not set session cookie: %s", exc)


def clear_session_token_cookie() -> None:
    try:
        cm = _manager()
        if cm is None:
            return
        cm.delete(SESSION_COOKIE_NAME, key=f"{_COOKIE_COMPONENT_KEY}_del")
    except KeyError:
        pass
    except Exception as exc:
        _log.warning("Could not clear session cookie: %s", exc)
