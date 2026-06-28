from __future__ import annotations

import pytest

from server.config import Settings
from server.engine.pool import ParsedToolCall
from server.orchestrator.tool_dispatch import run_main_tool_calls
from server.tools import build_tool_registry, build_tool_runner


@pytest.mark.asyncio
async def test_run_main_tool_calls_executes_and_preserves_call_id() -> None:
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    registry = build_tool_registry(settings)

    async def fake_search(*, user_id: str, query: str, max_results: int = 5, tavily_api_key=None):
        del user_id, query, max_results, tavily_api_key
        from server.tools.registry import ToolResult

        return ToolResult(status="ok", summary="ok", data={"results": []})

    entry = registry.get("web_search")
    assert entry is not None
    entry.fn = fake_search  # type: ignore[method-assign]
    runner = build_tool_runner(registry)

    calls = [
        ParsedToolCall(id="call_1", name="web_search", arguments='{"query":"nvidia"}')
    ]
    runs = await run_main_tool_calls(
        user_id="u1", turn_id="t1", tool_calls=calls, runner=runner
    )

    assert len(runs) == 1
    assert runs[0].call.id == "call_1"
    assert runs[0].result.status == "ok"


@pytest.mark.asyncio
async def test_run_main_tool_calls_rejects_non_main_tool() -> None:
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))
    calls = [ParsedToolCall(id="c1", name="deep_search", arguments="{}")]
    runs = await run_main_tool_calls(
        user_id="u1", turn_id="t1", tool_calls=calls, runner=runner
    )
    assert runs[0].result.status == "not_capable"
