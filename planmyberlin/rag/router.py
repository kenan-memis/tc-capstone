"""Retriever router: prefers Chroma when available, falls back to seed retrieval."""

from __future__ import annotations

from typing import Any

from planmyberlin.models import TripProfile
from planmyberlin.rag.chroma_store import chroma_index_ready, retrieve_chroma_context
from planmyberlin.rag.retrieve import retrieve_seed_context


def retrieve_context(profile: TripProfile, *, retrieval_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = retrieval_cfg or {}
    backend = str(cfg.get("backend", "auto")).lower()  # auto | seed | chroma
    limit = int(cfg.get("seed_limit", 8))
    persist_dir = cfg.get("chroma_persist_dir")
    collection_name = str(cfg.get("chroma_collection", "berlin_seed_v1"))

    if backend == "seed":
        payload = retrieve_seed_context(profile, limit=limit)
        payload["backend"] = "seed"
        return payload

    if backend in {"auto", "chroma"}:
        try:
            if chroma_index_ready(persist_dir=persist_dir, collection_name=collection_name):
                payload = retrieve_chroma_context(
                    profile,
                    limit=limit,
                    persist_dir=persist_dir,
                    collection_name=collection_name,
                )
                payload["backend"] = "chroma"
                return payload
            if backend == "chroma":
                raise RuntimeError("backend set to chroma but index is not ready")
        except Exception as exc:
            if backend == "chroma":
                raise
            payload = retrieve_seed_context(profile, limit=limit)
            payload["backend"] = "seed"
            payload["fallback_reason"] = str(exc)
            return payload

    payload = retrieve_seed_context(profile, limit=limit)
    payload["backend"] = "seed"
    return payload
