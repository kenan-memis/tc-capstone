# PlanMyBerlin (Capstone)

This project builds a **Berlin trip planning assistant** that combines curated knowledge with live APIs for transport, places, and weather. It uses **LangGraph** for agent-style orchestration (conditional routing and tool calls), **Streamlit** for the UI, and **YAML** for prompts and configuration. The assistant is **informational only**: it suggests where to go, how to move, what to eat, and where to stay using **links** — it does **not** perform bookings.

The repository currently contains an initial **LangGraph scaffold** with one conditional branch (accommodation vs no accommodation), YAML-backed settings and prompts, environment checks in Streamlit, and exported graph diagrams under `docs/graphs/`. Later milestones add hybrid RAG, external APIs (BVG, Places, weather), maps, and full itinerary generation.

## Run locally

```bash
uv sync --group dev
uv run streamlit run planmyberlin/ui/app.py
```

Export graph visuals (PNG + Mermaid):

```bash
uv run planmyberlin-export-graphs
```

Tests:

```bash
uv run pytest
```

Copy `.env.example` to `.env` and set API keys (`OPENAI_API_KEY`, and optionally `GEMINI_API_KEY` or `GOOGLE_API_KEY`). For production on Google Cloud Run, inject the **same variable names** via Secret Manager.
