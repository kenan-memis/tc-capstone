"""Retriever router: prefers Chroma when available, falls back to seed retrieval."""

from __future__ import annotations

from typing import Any

from planmyberlin.kb import canonical_borough, nearby_boroughs
from planmyberlin.models import TripProfile
from planmyberlin.rag.chroma_store import chroma_index_ready, retrieve_chroma_context
from planmyberlin.rag.retrieve import retrieve_seed_context


def _is_food_interest(label: str) -> bool:
    s = str(label).strip().lower()
    return any(k in s for k in ("food", "dining", "cafe", "coffee", "beer", "bar"))


def _is_food_item(item: dict[str, Any]) -> bool:
    category = str(item.get("category", "")).strip().lower()
    tags_raw = item.get("tags", [])
    tags: list[str]
    if isinstance(tags_raw, list):
        tags = [str(x).lower() for x in tags_raw]
    else:
        tags = [str(tags_raw).lower()]
    text = " ".join([category, *tags])
    return any(k in text for k in ("restaurant", "cafe", "coffee", "food", "bar", "beer"))


def _item_borough(item: dict[str, Any]) -> str:
    return canonical_borough(str(item.get("district", "")))


def _item_citation(item: dict[str, Any]) -> str:
    return (
        f"{item.get('name')} ({item.get('category')}, {item.get('district')})"
        f" — {item.get('source_file', 'unknown_source')}"
    )


def _apply_food_guarantee(
    payload: dict[str, Any],
    *,
    profile: TripProfile,
    cfg: dict[str, Any],
    limit: int,
    base_pool: list[dict[str, Any]],
) -> dict[str, Any]:
    food_guarantee = bool(cfg.get("food_interest_guarantee", True))
    food_min = max(1, int(cfg.get("food_interest_min_items", 2)))
    if not food_guarantee or not any(_is_food_interest(x) for x in profile.interest_tags):
        return payload

    chosen = list(payload.get("items", []))
    chosen_food = [it for it in chosen if _is_food_item(it)]
    need = max(0, food_min - len(chosen_food))
    if need <= 0:
        return payload

    food_candidates = [it for it in base_pool if _is_food_item(it) and it not in chosen]
    idx = len(chosen) - 1
    while need > 0 and food_candidates and idx >= 0:
        if not _is_food_item(chosen[idx]):
            chosen[idx] = food_candidates.pop(0)
            need -= 1
        idx -= 1
    payload["items"] = chosen[: max(1, limit)]
    payload["citations"] = [_item_citation(it) for it in payload["items"]]
    return payload


def _apply_area_filters(payload: dict[str, Any], profile: TripProfile, *, limit: int, cfg: dict[str, Any]) -> dict[str, Any]:
    items = list(payload.get("items", []))
    if not items:
        payload["retrieval_mode"] = "citywide"
        return payload

    selected = [x for x in profile.neighbourhoods if str(x).strip()]
    if not selected:
        payload["retrieval_mode"] = "citywide"
        payload["items"] = items[: max(1, limit)]
        payload["citations"] = [_item_citation(it) for it in payload["items"]]
        return _apply_food_guarantee(payload, profile=profile, cfg=cfg, limit=limit, base_pool=items)

    strict_enabled = bool(cfg.get("strict_area_filter", True))
    allow_nearby = bool(cfg.get("nearby_fallback", True))
    strict_min_items = max(1, int(cfg.get("strict_min_items", min(4, max(1, limit)))))

    if not strict_enabled:
        payload["retrieval_mode"] = "citywide"
        payload["items"] = items[: max(1, limit)]
        payload["citations"] = [_item_citation(it) for it in payload["items"]]
        return _apply_food_guarantee(payload, profile=profile, cfg=cfg, limit=limit, base_pool=items)

    selected_boroughs = {canonical_borough(x) for x in selected if canonical_borough(x) != "unknown"}
    strict_items = [it for it in items if _item_borough(it) in selected_boroughs]

    if len(strict_items) >= strict_min_items or not allow_nearby:
        chosen = strict_items[: max(1, limit)]
        payload["items"] = chosen
        payload["citations"] = [_item_citation(it) for it in chosen]
        payload["retrieval_mode"] = "strict"
        base_pool = strict_items
    else:
        nearby_borough_set = nearby_boroughs(selected_boroughs)
        nearby_fill = [
            it
            for it in items
            if _item_borough(it) in nearby_borough_set and it not in strict_items
        ]
        chosen = (strict_items + nearby_fill)[: max(1, limit)]
        payload["items"] = chosen
        payload["citations"] = [_item_citation(it) for it in chosen]
        payload["retrieval_mode"] = "nearby_fallback"
        base_pool = strict_items + nearby_fill

    return _apply_food_guarantee(payload, profile=profile, cfg=cfg, limit=limit, base_pool=base_pool)


def retrieve_context(profile: TripProfile, *, retrieval_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = retrieval_cfg or {}
    backend = str(cfg.get("backend", "auto")).lower()  # auto | seed | chroma
    limit = int(cfg.get("seed_limit", 8))
    candidate_limit = limit
    if bool(cfg.get("food_interest_guarantee", True)) and any(_is_food_interest(x) for x in profile.interest_tags):
        # Pull a wider candidate pool first, then enforce final top-k after filtering/guarantees.
        candidate_limit = max(limit * 4, 24)
    persist_dir = cfg.get("chroma_persist_dir")
    collection_name = str(cfg.get("chroma_collection", "berlin_seed_v1"))

    if backend == "seed":
        payload = retrieve_seed_context(profile, limit=candidate_limit)
        payload["backend"] = "seed"
        return _apply_area_filters(payload, profile, limit=limit, cfg=cfg)

    if backend in {"auto", "chroma"}:
        try:
            if chroma_index_ready(persist_dir=persist_dir, collection_name=collection_name):
                payload = retrieve_chroma_context(
                    profile,
                    limit=candidate_limit,
                    persist_dir=persist_dir,
                    collection_name=collection_name,
                )
                payload["backend"] = "chroma"
                return _apply_area_filters(payload, profile, limit=limit, cfg=cfg)
            if backend == "chroma":
                raise RuntimeError("backend set to chroma but index is not ready")
        except Exception as exc:
            if backend == "chroma":
                raise
            payload = retrieve_seed_context(profile, limit=candidate_limit)
            payload["backend"] = "seed"
            payload["fallback_reason"] = str(exc)
            return _apply_area_filters(payload, profile, limit=limit, cfg=cfg)

    payload = retrieve_seed_context(profile, limit=candidate_limit)
    payload["backend"] = "seed"
    return _apply_area_filters(payload, profile, limit=limit, cfg=cfg)
