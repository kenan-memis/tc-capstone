from planmyberlin.graph.workflow import build_planner_graph


def test_conditional_branch_accommodation() -> None:
    app = build_planner_graph()
    out = app.invoke({"needs_accommodation": True, "days": 2})
    assert out.get("branch_taken") == "accommodation"


def test_conditional_branch_no_accommodation() -> None:
    app = build_planner_graph()
    out = app.invoke({"needs_accommodation": False, "days": 1})
    assert out.get("branch_taken") == "no_accommodation"


def test_render_stub_prompt() -> None:
    from planmyberlin.prompts.loader import render_prompt

    text = render_prompt("stub_coach", "system")
    assert "PlanMyBerlin" in text
