# PlanMyBerlin (Capstone)

## Project description (evaluation)

- **Goal:** Help people plan a short Berlin visit with **structured, explainable suggestions** (places, food, transport, weather, events, optional stays) in one place, without pretending to book anything for them.
- **Problem it solves:** Trip planning is scattered across many sites; this app **aggregates** curated local knowledge, **retrieved context** (RAG), and **live signals** (weather, transport, cultural events) into a **day-by-day itinerary** the user can review and adjust.
- **How it works:** Users set trip parameters in a **Streamlit** UI. A **LangGraph** pipeline **normalises** the profile, **retrieves** from a **Chroma** (or seed) knowledge base, **enriches** place ideas, fetches **weather** and **events** (Kulturdaten API), builds **map** context and **transport** hints, runs **single- vs multi-day** logic, optionally adds **accommodation** ideas, then **generates** a structured itinerary via an LLM with constraints and grounding. **Signed-in users** can persist a **latest** run, **save multiple plans**, and mark **favourites** (SQLite). Everything remains **informational** (links and suggestions only).

The assistant is **informational only**: it suggests where to go, how to move, what to eat, and where to stay using **links** — it does **not** perform bookings. For **privacy and ethics**: passwords are **hashed**; session tokens are **revoked** on logout; the app does not sell user data; third-party APIs (maps, weather, events) are subject to their **providers’ terms** (users should verify hours, prices, and availability with official sources).

### Stack and architecture (summary)

- **LangGraph** workflow: normalize profile → **RAG** retrieval → enrich places → **weather** → **events** → **map** points → **transport** → multi/single-day **merge** → **accommodation** (optional) → **generate itinerary** → end.
- **RAG:** Structured seed corpus in `data/raw/`; retrieval mode `auto` / `chroma` / `seed` in settings.
- **Streamlit** UI: preferences, plan progress, map, detail panels, optional narrative; **user profiles** and **saved plans** in **SQLite** (`settings` → `profiles.sqlite_path`).

Deployment notes (e.g. Cloud Run, secrets) can be added in this section when ready.

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

## Docker (local)

From the project root, with `.env` present:

```bash
docker compose up --build
```

Open Streamlit at `http://localhost:8080`. Production images build with `INSTALL_DEV=false` (omit pytest/ruff); Compose sets `INSTALL_DEV=true` so you can optionally `docker compose run --rm app pytest` once a test command is wired into the image, or run tests on the host with `uv run pytest`.

The **Dockerfile** runs `planmyberlin-build-index` during the image build, so **production containers include the Chroma vector index** derived from `data/raw/` (no separate manual index step on the server unless you exclude `data/vectorstore/` from the image and choose to build at startup instead).

Build a production-style image locally:

```bash
docker build -t planmyberlin:prod .
```
