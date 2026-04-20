"""CLI to build/update local Chroma index from seed YAML corpus."""

from __future__ import annotations

import planmyberlin.env  # noqa: F401 - load .env for local usage

from planmyberlin.config.loader import get_settings
from planmyberlin.rag import build_chroma_index


def main() -> None:
    retrieval_cfg = get_settings().get("retrieval", {})
    result = build_chroma_index(
        persist_dir=retrieval_cfg.get("chroma_persist_dir"),
        collection_name=str(retrieval_cfg.get("chroma_collection", "berlin_seed_v1")),
        force=bool(retrieval_cfg.get("chroma_force_rebuild", False)),
    )
    print(result)


if __name__ == "__main__":
    main()
