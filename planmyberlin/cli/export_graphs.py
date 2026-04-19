"""Export LangGraph diagrams into ``docs/graphs/`` (PNG + Mermaid source)."""

from __future__ import annotations

from pathlib import Path


def main() -> None:
    """Write graph artifacts under repo ``docs/graphs/``."""
    # planmyberlin/cli/ → parents[2] is repo root (capstone-project)
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = repo_root / "docs" / "graphs"
    out_dir.mkdir(parents=True, exist_ok=True)

    from planmyberlin.graph.workflow import build_planner_graph

    app = build_planner_graph()
    graph = app.get_graph()

    png_path = out_dir / "planner_workflow.png"
    png_path.write_bytes(graph.draw_mermaid_png())

    mmd_path = out_dir / "planner_workflow.mmd"
    mmd_path.write_text(graph.draw_mermaid(), encoding="utf-8")

    print(f"Wrote {png_path}")
    print(f"Wrote {mmd_path}")


if __name__ == "__main__":
    main()
