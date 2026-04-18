"""Load YAML settings and constants packaged with `planmyberlin`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_CONFIG_DIR = Path(__file__).resolve().parent


def _read_yaml(name: str) -> dict[str, Any]:
    path = _CONFIG_DIR / name
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


@lru_cache
def get_settings() -> dict[str, Any]:
    """Return `settings.yaml` as a plain dict (expand to dataclasses later if useful)."""
    return _read_yaml("settings.yaml")


@lru_cache
def get_constants() -> dict[str, Any]:
    """Return `constants.yaml` as a plain dict."""
    return _read_yaml("constants.yaml")
