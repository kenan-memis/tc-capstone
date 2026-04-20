"""Chroma index build and retrieval over seed records."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from planmyberlin.models import TripProfile
from planmyberlin.rag.retrieve import load_seed_records


_DEFAULT_PERSIST_DIR = Path(__file__).resolve().parents[2] / "data" / "vectorstore" / "chroma"


def _persist_dir(path: str | None) -> Path:
    if not path:
        return _DEFAULT_PERSIST_DIR
    p = Path(path)
    if p.is_absolute():
        return p
    return Path(__file__).resolve().parents[2] / p


def _query_text(profile: TripProfile) -> str:
    return " | ".join(
        [
            f"interests: {', '.join(profile.interest_tags)}",
            f"districts: {', '.join(profile.neighbourhoods)}",
            f"budget: {profile.budget_tier}",
            f"pace: {profile.pace}",
            f"dietary: {profile.dietary_choice}",
            f"mobility: {profile.mobility_choice}",
            f"extra: {profile.extra_details}",
        ]
    )


def _dataset_fingerprint(records: list[dict[str, Any]]) -> str:
    serial = json.dumps(records, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(serial.encode("utf-8")).hexdigest()


def _fingerprint_file(persist_dir: Path, collection_name: str) -> Path:
    return persist_dir / f"{collection_name}.fingerprint"


def _to_documents(records: list[dict[str, Any]]) -> list[Document]:
    docs: list[Document] = []
    for rec in records:
        name = str(rec.get("name") or rec.get("title") or "")
        summary = str(rec.get("summary", ""))
        district = str(rec.get("district", ""))
        category = str(rec.get("category", ""))
        tags = ", ".join(str(t) for t in rec.get("tags", []))
        content = (
            f"Name: {name}\n"
            f"Category: {category}\n"
            f"District: {district}\n"
            f"Tags: {tags}\n"
            f"Summary: {summary}\n"
        )
        metadata = {
            "id": str(rec.get("id", "")),
            "name": name,
            "category": category,
            "district": district,
            "source_file": str(rec.get("source_file", "")),
            "summary": summary,
            "tags": tags,
        }
        docs.append(Document(page_content=content, metadata=metadata))
    return docs


def chroma_index_ready(*, persist_dir: str | None = None, collection_name: str = "berlin_seed_v1") -> bool:
    path = _persist_dir(persist_dir)
    if not path.exists():
        return False
    fp = _fingerprint_file(path, collection_name)
    return fp.exists() and any(path.rglob("*.sqlite3"))


def build_chroma_index(
    *,
    persist_dir: str | None = None,
    collection_name: str = "berlin_seed_v1",
    force: bool = False,
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required to build Chroma index with OpenAI embeddings")

    records = load_seed_records()
    fingerprint = _dataset_fingerprint(records)

    path = _persist_dir(persist_dir)
    path.mkdir(parents=True, exist_ok=True)
    fp_file = _fingerprint_file(path, collection_name)

    if fp_file.exists() and fp_file.read_text(encoding="utf-8").strip() == fingerprint and not force:
        return {
            "status": "up_to_date",
            "records": len(records),
            "persist_dir": str(path),
            "collection_name": collection_name,
        }

    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    docs = _to_documents(records)

    # Rebuild collection cleanly for deterministic seed-state behavior.
    vs = Chroma(
        collection_name=collection_name,
        persist_directory=str(path),
        embedding_function=embeddings,
    )
    try:
        vs.delete_collection()
    except Exception:
        pass

    Chroma.from_documents(
        documents=docs,
        collection_name=collection_name,
        persist_directory=str(path),
        embedding=embeddings,
    )

    fp_file.write_text(fingerprint, encoding="utf-8")
    return {
        "status": "rebuilt",
        "records": len(records),
        "persist_dir": str(path),
        "collection_name": collection_name,
    }


def retrieve_chroma_context(
    profile: TripProfile,
    *,
    limit: int = 8,
    persist_dir: str | None = None,
    collection_name: str = "berlin_seed_v1",
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for Chroma retrieval embeddings")

    path = _persist_dir(persist_dir)
    if not chroma_index_ready(persist_dir=str(path), collection_name=collection_name):
        raise RuntimeError("Chroma index is not ready; build index first")

    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    vs = Chroma(
        collection_name=collection_name,
        persist_directory=str(path),
        embedding_function=embeddings,
    )

    query = _query_text(profile)
    docs = vs.similarity_search(query=query, k=limit)

    items: list[dict[str, Any]] = []
    for d in docs:
        md = d.metadata or {}
        items.append(
            {
                "id": md.get("id"),
                "name": md.get("name"),
                "category": md.get("category"),
                "district": md.get("district"),
                "summary": md.get("summary", ""),
                "tags": md.get("tags", ""),
                "source_file": md.get("source_file"),
                "score": None,
            }
        )

    citations = [
        f"{it.get('name')} ({it.get('category')}, {it.get('district')}) — {it.get('source_file')}"
        for it in items
    ]

    return {
        "items": items,
        "citations": citations,
        "total_records": len(items),
        "backend": "chroma",
    }
