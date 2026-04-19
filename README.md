# PlanMyBerlin (Capstone)

This project builds a **Berlin trip planning assistant** that combines curated knowledge with live APIs for transport, places, and weather. It uses **LangGraph** for agent-style orchestration (conditional routing and tool calls), **Streamlit** for the UI, and **YAML** for prompts and configuration. The assistant is **informational only**: it suggests where to go, how to move, what to eat, and where to stay using **links** — it does **not** perform bookings.

The repository currently includes a **LangGraph workflow** (normalize profile → multi-day vs single-day branches → accommodation gate), a Streamlit **preferences form** (YAML-driven copy; predefined interests and Berlin areas), tests, exported diagrams under `docs/graphs/` (`planner_workflow.png`), and Docker. Later milestones add hybrid RAG, APIs (BVG, Places, weather), maps, and full itinerary generation.

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

## Docker (local, same layout as Sprint 3)

From this directory (`capstone-project/`), with `.env` present:

```bash
docker compose up --build
```

Open Streamlit at `http://localhost:8080`. Production images build with `INSTALL_DEV=false` (omit pytest/ruff); Compose sets `INSTALL_DEV=true` so you can optionally `docker compose run --rm app pytest` once a test command is wired into the image, or run tests on the host with `uv run pytest`.

Build a production-style image locally:

```bash
docker build -t planmyberlin:prod .
```
