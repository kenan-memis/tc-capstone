"""LangChain tools backed by planner state — used in the itinerary tool-calling phase."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool


def build_itinerary_tools(state: dict[str, Any]) -> list[Any]:
    """Return tool callables bound to this planning run's state (no extra HTTP)."""

    @tool
    def weather_digest() -> str:
        """Live weather summary, indoor/outdoor bias, and rough conditions for this Berlin plan run."""
        ws = str(state.get("weather_summary", "") or "").strip()
        wb = str(state.get("weather_bias", "unknown") or "unknown")
        cond = str(state.get("weather_condition_main", "") or "").strip()
        tc = state.get("weather_temperature_c")
        temp = float(tc) if isinstance(tc, (int, float)) else None
        payload = {
            "weather_summary": ws,
            "weather_bias": wb,
            "condition_main": cond,
            "temperature_c": temp,
        }
        return json.dumps(payload, ensure_ascii=False)

    @tool
    def candidate_places_digest(max_items: int = 12) -> str:
        """Structured list of retrieved / enriched Berlin places the itinerary may name (venues only from this list)."""
        max_items = max(1, min(int(max_items), 24))
        raw = list(state.get("enriched_items", [])) or list(state.get("retrieved_items", []))
        rows: list[dict[str, Any]] = []
        for item in raw[:max_items]:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "name": str(item.get("name", "")).strip(),
                    "category": str(item.get("category", "")).strip(),
                    "district": str(item.get("district", "")).strip(),
                    "summary": str(item.get("summary", ""))[:400],
                }
            )
        return json.dumps({"candidates": rows, "count": len(rows)}, ensure_ascii=False)

    @tool
    def transport_hints_digest(limit: int = 10) -> str:
        """Nearby transit lines and stops suggested for this plan (high level — no schedules)."""
        limit = max(1, min(int(limit), 20))
        items = state.get("transport_items", [])
        rows: list[dict[str, Any]] = []
        if isinstance(items, list):
            for it in items[:limit]:
                if not isinstance(it, dict):
                    continue
                rows.append(
                    {
                        "name": str(it.get("name", "")).strip(),
                        "type": str(it.get("type", "")).strip(),
                        "query": str(it.get("query", "")).strip(),
                    }
                )
        st = str(state.get("transport_status", ""))
        return json.dumps({"transport_status": st, "suggestions": rows, "count": len(rows)}, ensure_ascii=False)

    @tool
    def accommodation_links_digest(limit: int = 6) -> str:
        """Curated accommodation link ideas for this trip (informational links only — no booking)."""
        limit = max(1, min(int(limit), 10))
        items = state.get("accommodation_items", [])
        rows: list[dict[str, Any]] = []
        if isinstance(items, list):
            for it in items[:limit]:
                if not isinstance(it, dict):
                    continue
                rows.append(
                    {
                        "name": str(it.get("name", "")).strip(),
                        "type": str(it.get("type", "")).strip(),
                        "district": str(it.get("district", "")).strip(),
                        "reason": str(it.get("reason", ""))[:300],
                        "has_url": bool(str(it.get("url", "")).strip()),
                    }
                )
        st = str(state.get("accommodation_status", ""))
        return json.dumps({"accommodation_status": st, "stays": rows, "count": len(rows)}, ensure_ascii=False)

    @tool
    def retrieval_citations_digest(max_citations: int = 12) -> str:
        """Short citation lines from seed / vector retrieval for grounding tone and themes (not live POI facts)."""
        max_citations = max(1, min(int(max_citations), 30))
        cites = state.get("retrieved_citations", [])
        lines: list[str] = []
        if isinstance(cites, list):
            for c in cites[:max_citations]:
                s = str(c).strip()
                if s:
                    lines.append(s[:500])
        be = str(state.get("retrieval_backend", ""))
        n = state.get("retrieved_count")
        cnt = int(n) if isinstance(n, int) else None
        return json.dumps({"retrieval_backend": be, "retrieved_count": cnt, "citations": lines}, ensure_ascii=False)

    return [
        weather_digest,
        candidate_places_digest,
        transport_hints_digest,
        accommodation_links_digest,
        retrieval_citations_digest,
    ]
