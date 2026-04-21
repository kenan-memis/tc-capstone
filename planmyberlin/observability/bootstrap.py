"""Configure stdlib logging for PlanMyBerlin (plain or JSON lines)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from planmyberlin.observability.context import get_run_id

_CONFIGURED = False


class _RunContextFilter(logging.Filter):
    """Injects ``run_id`` on the log record from contextvars."""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = get_run_id()
        record.run_id = rid if rid else "-"
        return True


class _JsonFormatter(logging.Formatter):
    """One JSON object per line; suitable for Cloud Logging / log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "run_id": getattr(record, "run_id", None),
            "message": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    *,
    level: int = logging.INFO,
    json_logs: bool = False,
    force: bool = False,
) -> None:
    """Attach handlers to the root logger once (unless ``force``)."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    root = logging.getLogger()
    root.setLevel(level)

    # Replace our previous handler when re-configuring (tests / force).
    for h in list(root.handlers):
        if getattr(h, "_planmyberlin_handler", False):
            root.removeHandler(h)

    handler = logging.StreamHandler(sys.stderr)
    handler._planmyberlin_handler = True  # type: ignore[attr-defined]
    handler.addFilter(_RunContextFilter())
    if json_logs:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(levelname)s [%(run_id)s] %(name)s: %(message)s",
            )
        )
    root.addHandler(handler)

    # Reduce noisy third-party loggers in normal operation.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    _CONFIGURED = True


def configure_logging_from_settings(*, force: bool = False) -> None:
    """Read ``observability`` from ``settings.yaml`` and configure logging."""
    from planmyberlin.config.loader import get_settings

    raw = get_settings().get("observability", {})
    if not isinstance(raw, dict):
        raw = {}
    name = str(raw.get("log_level", "INFO")).upper()
    level = getattr(logging, name, logging.INFO)
    json_logs = bool(raw.get("json_logs", False))
    configure_logging(level=level, json_logs=json_logs, force=force)


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``planmyberlin`` namespace."""
    return logging.getLogger(name)
