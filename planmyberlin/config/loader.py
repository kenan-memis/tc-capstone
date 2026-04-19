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


def _read_yaml_list(name: str, *, key: str = "items") -> list[str]:
    path = _CONFIG_DIR / name
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and key in raw:
        block = raw[key]
        if isinstance(block, list):
            return [str(x).strip() for x in block if str(x).strip()]
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


@lru_cache
def get_settings() -> dict[str, Any]:
    """Return `settings.yaml` as a plain dict (expand to dataclasses later if useful)."""
    return _read_yaml("settings.yaml")


@lru_cache
def get_constants() -> dict[str, Any]:
    """Return `constants.yaml` as a plain dict."""
    return _read_yaml("constants.yaml")


@lru_cache
def get_interest_options() -> tuple[str, ...]:
    """Labels for the interests multiselect (from `interest_options.yaml`)."""
    return tuple(_read_yaml_list("interest_options.yaml"))


@lru_cache
def get_neighbourhood_options() -> tuple[str, ...]:
    """Labels for the Berlin areas multiselect (from `neighbourhood_options.yaml`)."""
    return tuple(_read_yaml_list("neighbourhood_options.yaml"))


@lru_cache
def get_dietary_options() -> tuple[str, ...]:
    """Single-choice dietary labels (`dietary_options.yaml`)."""
    return tuple(_read_yaml_list("dietary_options.yaml"))


@lru_cache
def get_mobility_options() -> tuple[str, ...]:
    """Single-choice mobility/accessibility hints (`mobility_options.yaml`)."""
    return tuple(_read_yaml_list("mobility_options.yaml"))
