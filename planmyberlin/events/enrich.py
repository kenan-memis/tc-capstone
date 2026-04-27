"""Optional English blurbs for event rows (uses OPENAI_API_KEY when set)."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from planmyberlin.config.loader import get_settings


def _fallback_info_en(item: dict[str, Any]) -> str:
    summ = str(item.get("summary", "")).strip()
    adm = str(item.get("admission_hint_en", "")).strip()
    if summ and _mostly_latin_or_english(summ):
        return summ[:320]
    if adm:
        return adm
    if summ:
        return summ[:320]
    return "Cultural event in Berlin."


def _mostly_latin_or_english(text: str) -> bool:
    if not text:
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    non_ascii = sum(1 for c in letters if ord(c) > 127)
    return non_ascii / len(letters) < 0.15


def attach_english_insights(events_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adds ``info_en`` per row: translated/polished English insight when OpenAI is configured."""
    if not events_items:
        return events_items

    out = [dict(x) for x in events_items]
    if not str(os.getenv("OPENAI_API_KEY", "")).strip():
        for item in out:
            item["info_en"] = _fallback_info_en(item)
        return out

    settings = get_settings()
    model = str(settings.get("models", {}).get("openai_default", "gpt-4o-mini"))

    chunks: list[str] = []
    for idx, item in enumerate(out):
        blob = str(item.get("hints_blob", "")).strip()
        name = str(item.get("name", "")).strip()
        venue = str(item.get("venue", "")).strip()
        pieces = [p for p in [name, venue, blob] if p]
        chunks.append(" | ".join(pieces)[:1800])

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=model, temperature=0.2)
        sys = SystemMessage(
            content=(
                "You write short English blurbs for tourists visiting Berlin. "
                "Given fragments about a cultural event (possibly in German), "
                "output ONE clear English sentence per event (max 260 characters each), "
                "explaining what the event is. Keep proper nouns; translate the rest. "
                "Respond with JSON only: {\"insights\": [\"...\", ...]} — same length and "
                "order as the input array."
            )
        )
        human = HumanMessage(
            content=json.dumps({"events": chunks}, ensure_ascii=False),
        )
        resp = llm.invoke([sys, human])
        raw = str(resp.content).strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise ValueError("no json")
        parsed = json.loads(m.group())
        insights = parsed.get("insights")
        if not isinstance(insights, list) or len(insights) != len(out):
            raise ValueError("insights length mismatch")
        for item, insight in zip(out, insights):
            text = str(insight).strip() if insight is not None else ""
            item["info_en"] = text[:320] if text else _fallback_info_en(item)
    except Exception:
        for item in out:
            item.setdefault("info_en", _fallback_info_en(item))

    return out
