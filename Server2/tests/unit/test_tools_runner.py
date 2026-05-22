from __future__ import annotations

import asyncio

import pytest

from server.tools.registry import ToolCall, ToolEntry, ToolRegistry, ToolResult
from server.tools.runner import ToolRunner, require_confirmation, verify_confirmation


async def _slow_tool(*, user_id: str) -> ToolResult:
    del user_id
    await asyncio.sleep(2.0)
    return ToolResult(status="ok", summary="late")


async def _ok_tool(*, user_id: str) -> ToolResult:
    del user_id
    return ToolResult(status="ok", summary="done", data={"x": 1})


@pytest.mark.asyncio
async def test_runner_timeout() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolEntry(
            name="slow",
            capability="main",
            description="slow",
            args_schema={"type": "object", "properties": {}},
            fn=_slow_tool,
            timeout_s=1,
        )
    )
    runner = ToolRunner(registry)
    result = await runner.execute(
        "turn-1",
        ToolCall(name="slow", args={}, capability="main"),
        user_id="u1",
    )
    assert result.status == "error"
    assert "timed out" in result.summary


@pytest.mark.asyncio
async def test_runner_not_capable_wrong_capability() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolEntry(
            name="web_search",
            capability="main",
            description="search",
            args_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
            fn=_ok_tool,
        )
    )
    runner = ToolRunner(registry)
    result = await runner.execute(
        "turn-1",
        ToolCall(name="web_search", args={"query": "x"}, capability="research"),
        user_id="u1",
    )
    assert result.status == "not_capable"


@pytest.mark.asyncio
async def test_runner_emits_events() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolEntry(
            name="ping",
            capability="main",
            description="ping",
            args_schema={"type": "object", "properties": {}},
            fn=_ok_tool,
        )
    )
    runner = ToolRunner(registry)
    events: list[tuple[str, str, str]] = []

    async def on_event(kind: str, task_id: str, summary: str) -> None:
        events.append((kind, task_id, summary))

    await runner.execute(
        "tid-9",
        ToolCall(name="ping", args={}, capability="main"),
        user_id="u1",
        on_event=on_event,
    )
    assert events[0][0] == "tool_started"
    assert events[1][0] == "tool_done"
    assert events[0][1] == "tid-9"


def test_confirmation_required_shape() -> None:
    call = ToolCall(name="send_mail", args={"to": "a@b.com"}, capability="main")
    result = require_confirmation(call, preview={"to": "a@b.com"})
    assert result.status == "confirmation_required"
    assert result.confirmation is not None
    assert result.confirmation["id"].startswith("confirm_")


def test_verify_confirmation_requires_confirmed_flag() -> None:
    call = ToolCall(
        name="send_mail",
        args={"confirmed": True, "confirmation_id": "confirm_abc"},
        capability="main",
    )
    assert verify_confirmation("confirm_abc", call) is True
    assert verify_confirmation("bad", call) is False
