"""Tests for logging bootstrap and run correlation."""

from __future__ import annotations

import json
import logging

import pytest

from planmyberlin.observability import bind_run_context, configure_logging, get_logger, get_run_id


def test_bind_run_context_restores_previous() -> None:
    assert get_run_id() is None
    with bind_run_context("rid-test"):
        assert get_run_id() == "rid-test"
    assert get_run_id() is None


def test_plain_logs_include_run_id(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level=logging.INFO, json_logs=False, force=True)
    log = get_logger("tests.planmyberlin.observability_plain")
    with bind_run_context("corr-aaa"):
        log.info("probe_plain_message")
    err = capsys.readouterr().err
    assert "corr-aaa" in err
    assert "probe_plain_message" in err


def test_json_logs_are_single_line_objects(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level=logging.INFO, json_logs=True, force=True)
    log = get_logger("tests.planmyberlin.observability_json")
    with bind_run_context("corr-bbb"):
        log.info("probe_json_message")
    err = capsys.readouterr().err
    match = next(ln for ln in err.splitlines() if "probe_json_message" in ln)
    payload = json.loads(match.strip())
    assert payload["run_id"] == "corr-bbb"
    assert "probe_json_message" in payload["message"]
