"""Deterministic seed retrieval over structured YAML records.

This remains the fallback path even after adding Chroma.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from planmyberlin.config.loader import get_interest_coverage_matrix
from planmyberlin.models import TripProfile

_SEED_ROOT = Path(__file__).resolve().parents[2] / "data" / "raw"
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


@lru_cache
def load_seed_records() -> list[dict[str, Any]]:
    """Load and normalize YAML records under `data/raw` into flat dictionaries."""
    records: list[dict[str, Any]] = []
    for path in sorted(_SEED_ROOT.glob("**/*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        district = str(data.get("district", "")).strip()
        category = str(data.get("category", "")).strip() or path.parent.name
        items = data.get("items", [])
        if not isinstance(items, list):
            continue
        for raw in items:
            if not isinstance(raw, dict):
                continue
            rec = dict(raw)
            rec.setdefault("district", district)
            rec.setdefault("category", category)
            rec.setdefault("source_file", str(path.relative_to(_SEED_ROOT.parent)))
            rec["_search_name"] = str(rec.get("name") or rec.get("title") or "")
            rec["_search_tags"] = [str(t).lower() for t in rec.get("tags", []) if str(t).strip()]
            rec["_search_district"] = str(rec.get("district", "")).lower()
            records.append(rec)
    return records


def _tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}


def _interest_keywords(profile: TripProfile) -> set[str]:
    kw: set[str] = set()
    for label in profile.interest_tags:
        kw.update(_tokens(label))
    return {k for k in kw if len(k) >= 4}


def _district_keywords(profile: TripProfile) -> set[str]:
    kw: set[str] = set()
    for label in profile.neighbourhoods:
        kw.update(_tokens(label))
    return {k for k in kw if len(k) >= 4}


def _interest_intent(profile: TripProfile) -> dict[str, set[str]]:
    matrix = get_interest_coverage_matrix()
    cats: set[str] = set()
    tags: set[str] = set()
    for label in profile.interest_tags:
        row = matrix.get(label, {})
        cats.update(str(x).lower() for x in row.get("categories", []))
        tags.update(str(x).lower() for x in row.get("tags", []))
        # fallback to tokenized interest words for unseen labels
        tags.update(_tokens(label))
    return {"categories": cats, "tags": {t for t in tags if len(t) >= 3}}


def _score_record(
    rec: dict[str, Any], *, interest_kw: set[str], district_kw: set[str], intent: dict[str, set[str]]
) -> float:
    score = 0.0
    record_district_tokens = _tokens(rec.get("district", ""))
    if district_kw:
        overlap = record_district_tokens.intersection(district_kw)
        if overlap:
            score += 4.0
        else:
            score -= 1.0

    tag_kw = set(rec.get("_search_tags", []))
    name_kw = _tokens(rec.get("_search_name", ""))
    overlap = interest_kw.intersection(tag_kw.union(name_kw))
    score += float(len(overlap)) * 1.5

    # Explicit interest coverage matrix boosts.
    category = str(rec.get("category", "")).lower()
    if intent["categories"] and category in intent["categories"]:
        score += 1.0
    if intent["tags"]:
        tag_overlap = intent["tags"].intersection(tag_kw.union(name_kw))
        score += float(len(tag_overlap)) * 0.8

    category = str(rec.get("category", ""))
    if category in {"places", "restaurants"}:
        score += 0.3

    return score


def retrieve_seed_context(profile: TripProfile, *, limit: int = 8) -> dict[str, Any]:
    """Return ranked seed records with lightweight source metadata."""
    records = load_seed_records()
    interest_kw = _interest_keywords(profile)
    district_kw = _district_keywords(profile)
    intent = _interest_intent(profile)

    ranked = sorted(
        ((rec, _score_record(rec, interest_kw=interest_kw, district_kw=district_kw, intent=intent)) for rec in records),
        key=lambda x: x[1],
        reverse=True,
    )

    top: list[dict[str, Any]] = []
    for rec, score in ranked:
        if len(top) >= limit:
            break
        if score < 0.0:
            continue
        top.append(
            {
                "id": rec.get("id"),
                "name": rec.get("name") or rec.get("title"),
                "category": rec.get("category"),
                "district": rec.get("district"),
                "summary": rec.get("summary", ""),
                "tags": rec.get("tags", []),
                "source_file": rec.get("source_file"),
                "score": round(float(score), 3),
            }
        )

    citations = [
        f"{it.get('name')} ({it.get('category')}, {it.get('district')}) — {it.get('source_file')}"
        for it in top
    ]

    return {
        "items": top,
        "citations": citations,
        "total_records": len(records),
        "backend": "seed",
    }
