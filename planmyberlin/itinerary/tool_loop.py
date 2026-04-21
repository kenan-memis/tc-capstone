"""Bounded tool-calling loop for the itinerary LLM (evidence gathering before structured output)."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from planmyberlin.observability import get_logger

_log = get_logger(__name__)


def _tool_call_field(tc: Any, key: str) -> Any:
    if isinstance(tc, dict):
        return tc.get(key)
    return getattr(tc, key, None)


def run_itinerary_tool_loop(
    llm: BaseChatModel,
    tools: list[Any],
    *,
    system: str,
    human: str,
    max_rounds: int,
) -> str:
    """Run tool calls until the model stops requesting tools or ``max_rounds`` is reached.

    Returns assistant text (short plan / checklist) to optionally append before structured generation.
    """
    if not tools or max_rounds < 1:
        return ""

    by_name = {t.name: t for t in tools}

    messages: list[Any] = [SystemMessage(content=system), HumanMessage(content=human)]
    scratchpad = ""

    for round_idx in range(max_rounds):
        ai_msg = llm.bind_tools(tools).invoke(messages)
        messages.append(ai_msg)
        if not isinstance(ai_msg, AIMessage):
            break

        tool_calls = ai_msg.tool_calls or []
        if not tool_calls:
            scratchpad = str(ai_msg.content or "").strip()
            _log.info("itinerary_tool_loop stop round=%s tool_calls=0", round_idx + 1)
            break

        _log.info(
            "itinerary_tool_loop round=%s tool_calls=%s names=%s",
            round_idx + 1,
            len(tool_calls),
            [_tool_call_field(tc, "name") for tc in tool_calls],
        )

        for tc in tool_calls:
            name = str(_tool_call_field(tc, "name") or "")
            tid = str(_tool_call_field(tc, "id") or "")
            args = _tool_call_field(tc, "args") or {}
            if not isinstance(args, dict):
                args = {}
            tool_obj = by_name.get(name)
            if tool_obj is None:
                payload = json.dumps({"error": f"unknown_tool:{name}"})
            else:
                try:
                    payload = tool_obj.invoke(args)
                except Exception as exc:
                    payload = json.dumps({"error": type(exc).__name__, "detail": str(exc)})
            messages.append(ToolMessage(content=str(payload), tool_call_id=tid))

    if not scratchpad:
        for m in reversed(messages):
            if isinstance(m, AIMessage):
                content = str(m.content or "").strip()
                if content:
                    scratchpad = content
                    break

    if scratchpad:
        _log.info("itinerary_tool_loop scratchpad_chars=%s", len(scratchpad))
    else:
        _log.warning("itinerary_tool_loop empty_scratchpad")

    return scratchpad
