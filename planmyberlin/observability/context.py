"""Per-request correlation id for logs (optional LangGraph RunnableConfig metadata)."""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Iterator

_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("planmyberlin_run_id", default=None)


def get_run_id() -> str | None:
    return _run_id.get()


@contextmanager
def bind_run_context(run_id: str) -> Iterator[str]:
    token = _run_id.set(run_id)
    try:
        yield run_id
    finally:
        _run_id.reset(token)
