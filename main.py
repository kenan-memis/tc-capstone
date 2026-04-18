"""CLI entry for local runs; Streamlit is the primary UI (`planmyberlin.ui.app`)."""

import planmyberlin.env  # noqa: F401 — load `.env` for development


def main() -> None:
    print("PlanMyBerlin — run the Streamlit UI with:")
    print("  uv run streamlit run planmyberlin/ui/app.py")
    print()
    print("Export LangGraph diagrams with:")
    print("  uv run planmyberlin-export-graphs")


if __name__ == "__main__":
    main()
