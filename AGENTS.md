# AGENTS.md — PlanMyBerlin (Capstone)

Guidance for AI coding agents and contributors. This file lives at the **git repository root** (`capstone-project`).

## Product

- **Name:** PlanMyBerlin  
- **Purpose:** Berlin trip planning assistant — what to do, how to get around, where to eat, where to stay (suggestions + **links only**; **no booking**).

## Repository layout (this repo)

- Application code, `pyproject.toml`, `uv.lock` — **uv** project.  
- **LangGraph diagram exports:** `docs/graphs/` (committed PNG/SVG; regenerate when the graph topology changes).  
- Optional: if you keep a local planning “shell” one level up (not in git), path references there are for your notes only.

## Engineering constraints (non-negotiables)

1. **LangGraph-first** orchestration with **conditional routing** (not a fixed linear pipeline).
2. **LLM-orchestrated tool use** where appropriate (`bind_tools` / tool-calling loops) — behavior must be demonstrably agentic.
3. **Hybrid RAG + live APIs:** curated corpus for grounding; APIs for volatile facts (transport, places, weather). Resolve conflicts explicitly in orchestrator logic.
4. **Live API baseline:** BVG REST (transit), Google Places (POI/geocoding), Folium + `streamlit-folium` (maps), OpenWeatherMap (weather).
5. **Streamlit UI** with **streaming** (tokens and/or graph step events) and clear progress.
6. **Prompts / constants / tunable parameters** in **YAML**, loaded via a typed config layer — avoid huge inline prompt strings in orchestration code.
7. **Graph visuals** exported into **`docs/graphs/`** for reviewers.
8. **Automated tests** (unit + integration with mocked HTTP/LLM); no shipping without critical-path coverage.
9. **Reliability & safety:** timeouts/retries on external calls; classify errors; do not expose raw exception strings to end users; layered prompt-injection defenses and safe rendering.

## Accommodation routing

- **Multi-day:** suggest accommodation by default unless user opts out.  
- **Single-day:** no default accommodation; include only if the user indicates need or enables it.  
- **Never** booking — links and planning only.

## Commands (uv)

```bash
uv sync
uv run python main.py
```

(Add `uv run streamlit ...` once the UI module exists.)

## When changing the LangGraph

- Update or add exports under `docs/graphs/`.  
- Prefer a small script (e.g. `scripts/export_graph_visuals.py`) once the graph module exists.

## Out of scope

- Booking or payments for hotels, restaurants, museums, or tickets.
