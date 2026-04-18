"""Load prompts from YAML and render simple `{placeholder}` templates."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_PROMPTS_PATH = Path(__file__).resolve().parent / "prompts.yaml"


@lru_cache
def _prompts_raw() -> dict[str, Any]:
    raw = yaml.safe_load(_PROMPTS_PATH.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def render_prompt(section: str, field: str, **kwargs: Any) -> str:
    """Return a prompt string from `prompts.yaml` → section → field with `.format(**kwargs)`."""
    block = _prompts_raw().get(section)
    if not isinstance(block, dict):
        raise KeyError(f"Unknown prompt section: {section!r}")
    template = block.get(field)
    if template is None:
        raise KeyError(f"Unknown prompt field: {section}.{field}")
    text = str(template).strip()
    return text.format(**kwargs) if kwargs else text
