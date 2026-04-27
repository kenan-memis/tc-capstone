"""Pytest defaults: keep graph tests from calling the network/LLM for event enrichment."""

import pytest

import planmyberlin.graph.workflow as wf


@pytest.fixture(autouse=True)
def _stub_event_english_enrich(monkeypatch: pytest.MonkeyPatch) -> None:
    def _apply(items: list) -> list:
        out: list = []
        for it in items:
            d = dict(it)
            d.setdefault(
                "info_en",
                (d.get("summary") or "Cultural event in Berlin during your selected dates.")[:320],
            )
            out.append(d)
        return out

    monkeypatch.setattr(wf, "attach_english_insights", _apply)
