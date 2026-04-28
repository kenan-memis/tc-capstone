# PlanMyBerlin (Capstone)

## Project description

- **Goal:** Help people plan a short Berlin visit with **structured, explainable suggestions** (places, food, transport, weather, events, optional stays) in one place, without pretending to book anything for them.
- **Problem it solves:** Trip planning is scattered across many sites; this app **aggregates** curated local knowledge, **retrieved context** (RAG), and **live signals** (weather, transport, cultural events) into a **day-by-day itinerary** the user can review and adjust.
- **How it works:** Users set trip parameters in a **Streamlit** UI. A **LangGraph** pipeline **normalises** the profile, **retrieves** from a **Chroma** (or seed) knowledge base, **enriches** place ideas, fetches **weather** and **events** (Kulturdaten API), builds **map** context and **transport** hints, runs **single- vs multi-day** logic, optionally adds **accommodation** ideas, then **generates** a structured itinerary via an LLM with constraints and grounding. **Signed-in users** can persist a **latest** run, **save multiple plans**, and mark **favourites** (SQLite). Everything remains **informational** (links and suggestions only).

The assistant is **informational only**: it suggests where to go, how to move, what to eat, and where to stay using **links** — it does **not** perform bookings. For **privacy and ethics**: passwords are **hashed**; session tokens are **revoked** on logout; the app does not sell user data; third-party APIs (maps, weather, events) are subject to their **providers' terms** (users should verify hours, prices, and availability with official sources).

### Stack and architecture (summary)

- **LangGraph** workflow: normalize profile -> **RAG** retrieval -> enrich places -> **weather** -> **events** -> **map** points -> **transport** -> multi/single-day **merge** -> **accommodation** (optional) -> **generate itinerary** -> end.
- **RAG:** Structured seed corpus in `data/raw/`; retrieval mode `auto` / `chroma` / `seed` in settings.
- **Streamlit** UI: preferences, plan progress, map, detail panels, optional narrative; **user profiles** and **saved plans** in **SQLite** (`settings` -> `profiles.sqlite_path`).

---

## How it is built

| Area | Stack |
|------|--------|
| **Language** | Python 3.11+ (see `pyproject.toml`; Docker image uses 3.13) |
| **Environment & deps** | [`uv`](https://github.com/astral-sh/uv) + `pyproject.toml` / `uv.lock` (no `requirements.txt`) |
| **UI** | [Streamlit](https://streamlit.io/) — single-page app |
| **Orchestration** | [LangGraph](https://langchain-ai.github.io/langgraph/) planner workflow |
| **LLMs** | OpenAI (default), optional Gemini key paths in env |
| **Config** | YAML in `planmyberlin/config/`, prompts in `planmyberlin/prompts/prompts.yaml` |
| **Persistence** | SQLite profile/session/plan store under `data/app/` |

---

## Project structure

```text
capstone-project/
├── README.md
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── docker-compose.yml
├── docker-entrypoint.sh
├── .env.example
├── docs/
│   └── graphs/
│       └── planner_workflow.mmd
├── planmyberlin/
│   ├── ui/app.py
│   ├── graph/workflow.py
│   ├── rag/
│   ├── itinerary/
│   ├── places/client.py
│   ├── weather/client.py
│   ├── transport/client.py
│   ├── events/client.py
│   ├── accommodation/client.py
│   ├── profiles/
│   ├── prompts/
│   └── config/
├── data/
│   ├── raw/
│   ├── vectorstore/
│   └── app/
└── tests/
```

---

## System dependencies

You need the following installed on your machine:

- **Git**
- **Docker** (Docker Desktop or Docker Engine **with Compose V2**: `docker compose …`)

Optional (runs app/tests/lint on the host without Docker):

- **[uv](https://github.com/astral-sh/uv)**

---

## Getting started

Clone the repository (replace with your fork or remote):

```bash
git clone <your-repo-url>
cd capstone-project
```

---

## Configure API keys (local)

Copy the example env file and add your keys:

```bash
cp .env.example .env
```

Edit `.env` (minimum set depends on the features you run):

```text
OPENAI_API_KEY=...
OPENWEATHER_API_KEY=...
GOOGLE_PLACES_API_KEY=...
SERPAPI_API_KEY=...
```

`GEMINI_API_KEY` / `GOOGLE_API_KEY` are optional in current code paths. Keep **`.env` out of version control**.

---

## Development (Docker)

From the repo root, with Docker running:

```bash
docker compose up -d
docker compose ps
```

Open the app at **http://localhost:8080**.

The Compose file builds with **`INSTALL_DEV=true`** so the same image can run **lint** and **tests**. Production-style images built via `docker build` use **`INSTALL_DEV=false`**.

---

## Run locally without Docker

```bash
uv sync --group dev
uv run streamlit run planmyberlin/ui/app.py
```

---

## Linting

[Ruff](https://docs.astral.sh/ruff/) is configured in `pyproject.toml`.

Using Docker Compose:

```bash
docker compose run --rm --entrypoint "" app uv run ruff check planmyberlin tests
```

Using uv on the host:

```bash
uv sync --group dev
uv run ruff check planmyberlin tests
```

---

## Running tests

Tests use **[pytest](https://pytest.org/)**.

Using Docker Compose:

```bash
docker compose run --rm --entrypoint "" app uv run pytest tests/
```

Using uv on the host:

```bash
uv sync --group dev
uv run pytest tests/
```

---

## Useful project commands

Export graph visuals (PNG + Mermaid):

```bash
uv run planmyberlin-export-graphs
```

Build/update local Chroma index from seed data:

```bash
uv run planmyberlin-build-index
```

Build a production-style image locally:

```bash
docker build -t planmyberlin:prod .
```

---

## Deployment

**Live app (production):** [https://planmyberlin-671153735897.europe-west10.run.app/](https://planmyberlin-671153735897.europe-west10.run.app/)

---

## Observability (LangSmith tracing)

- LangGraph planner runs are instrumented with LangSmith tracing (including per-node timing in waterfall view).
- Tracing works in local development and can be enabled in Cloud Run via environment variables / secrets.
- Current trace project name: `planmyberlin`.

---

## Privacy, ethics, and limitations

- This app is **informational only**; it does not perform reservations or purchases.
- Users should verify opening hours, prices, and availability with official providers.
- Passwords are hashed; sessions are revocable; profile/plan data is stored in SQLite.
- External API quality and availability can affect results.

---

## Course context

This project is part of the **Turing College AI Engineering** capstone and is for learning and portfolio purposes.
