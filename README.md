# PlanMyBerlin (Capstone)

This project builds a **Berlin trip planning assistant** that combines curated knowledge with live APIs for transport, places, and weather. It uses **LangGraph** for agent-style orchestration (conditional routing and tool calls), **Streamlit** for the UI, and **YAML** for prompts and configuration. The assistant is **informational only**: it suggests where to go, how to move, what to eat, and where to stay using **links** — it does **not** perform bookings.

The repository currently includes a **LangGraph workflow** (normalize profile → retrieval → places enrichment → weather signal → map points → transport context → multi-day vs single-day branches → accommodation gate), a Streamlit **preferences form** (YAML-driven copy; predefined interests and Berlin areas), and a **structured seed RAG corpus** under `data/raw/` for places/restaurants/transport context. Retrieval backend is configurable: `auto` (prefer Chroma index if available, fallback to seed), `chroma`, or `seed`. Places enrichment is backend-configurable (`google_places` preferred, `serpapi` optional), weather uses OpenWeather (`OPENWEATHER_API_KEY`), and transport suggestions use a transport.rest-compatible BVG endpoint. Retrieved/enriched items and weather bias are shown in the preview for transparency. When coordinates are available, the UI also renders an interactive map preview with markers.

## Run locally

```bash
uv sync --group dev
uv run streamlit run planmyberlin/ui/app.py
```

Export graph visuals (PNG + Mermaid):

```bash
uv run planmyberlin-export-graphs
```

Build/update local Chroma index from seed data:

```bash
uv run planmyberlin-build-index
```


Tests:

```bash
uv run pytest
```

Copy `.env.example` to `.env` and set API keys (`OPENAI_API_KEY`, optionally `GEMINI_API_KEY` / `GOOGLE_API_KEY`, `OPENWEATHER_API_KEY`, and `SERPAPI_API_KEY`). For production on Google Cloud Run, inject the **same variable names** via Secret Manager.

## Docker (local, same layout as Sprint 3)

From this directory (`capstone-project/`), with `.env` present:

```bash
docker compose up --build
```

Open Streamlit at `http://localhost:8080`. Production images build with `INSTALL_DEV=false` (omit pytest/ruff); Compose sets `INSTALL_DEV=true` so you can optionally `docker compose run --rm app pytest` once a test command is wired into the image, or run tests on the host with `uv run pytest`.

The **Dockerfile** runs `planmyberlin-build-index` during the image build, so **production containers include the Chroma vector index** derived from `data/raw/` (no separate manual index step on the server unless you exclude `data/vectorstore/` from the image and choose to build at startup instead).

Build a production-style image locally:

```bash
docker build -t planmyberlin:prod .
```
