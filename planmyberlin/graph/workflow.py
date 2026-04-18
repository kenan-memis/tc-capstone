"""Minimal LangGraph with conditional routing (Option B scaffold).

Demonstrates orchestrator-style branching on `needs_accommodation`. Full trip logic
lands in later milestones.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph


class PlannerState(TypedDict, total=False):
    """Graph state for the stub planner."""

    days: int
    needs_accommodation: bool
    branch_taken: Literal["accommodation", "no_accommodation"]


def _preflight(state: PlannerState) -> PlannerState:
    """Pass-through; routing reads `needs_accommodation` from input."""
    return dict(state)


def _with_accommodation(state: PlannerState) -> PlannerState:
    out = dict(state)
    out["branch_taken"] = "accommodation"
    return out


def _without_accommodation(state: PlannerState) -> PlannerState:
    out = dict(state)
    out["branch_taken"] = "no_accommodation"
    return out


def _route_accommodation(state: PlannerState) -> Literal["accommodation", "no_accommodation"]:
    if state.get("needs_accommodation"):
        return "accommodation"
    return "no_accommodation"


def build_planner_graph():
    """Compile the stub planner graph (single conditional edge after preflight)."""
    g = StateGraph(PlannerState)
    g.add_node("preflight", _preflight)
    g.add_node("accommodation", _with_accommodation)
    g.add_node("no_accommodation", _without_accommodation)

    g.add_edge(START, "preflight")
    g.add_conditional_edges(
        "preflight",
        _route_accommodation,
        {"accommodation": "accommodation", "no_accommodation": "no_accommodation"},
    )
    g.add_edge("accommodation", END)
    g.add_edge("no_accommodation", END)

    return g.compile()
