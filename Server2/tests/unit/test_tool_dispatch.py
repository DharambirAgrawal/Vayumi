from __future__ import annotations

import asyncio

import pytest

from server.config import Settings
from server.orchestrator.directives import DelegateDirective
from server.orchestrator.tool_dispatch import run_delegate_directives
from server.tools import build_tool_registry, build_tool_runner


@pytest.mark.asyncio
async def test_parallel_main_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    registry = build_tool_registry(settings)
    runner = build_tool_runner(registry)

    delays: list[str] = []

    async def slow_search(*, user_id: str, query: str, max_results: int = 5, tavily_api_key=None):
        del user_id, query, max_results, tavily_api_key
        delays.append("start")
        await asyncio.sleep(0.05)
        delays.append("end")
        from server.tools.registry import ToolResult

        return ToolResult(status="ok", summary="ok", data={"results": []})

    entry = registry.get("web_search")
    assert entry is not None
    entry.fn = slow_search  # type: ignore[method-assign]

    directives = [
        DelegateDirective(
            capability="main",
            goal="one",
            payload={"tool": "web_search", "args": {"query": "a"}},
        ),
        DelegateDirective(
            capability="main",
            goal="two",
            payload={"tool": "web_search", "args": {"query": "b"}},
        ),
    ]

    started = asyncio.get_event_loop().time()
    runs = await run_delegate_directives(
        user_id="u1",
        turn_id="turn-par",
        directives=directives,
        runner=runner,
    )
    elapsed = asyncio.get_event_loop().time() - started

    assert len(runs) == 2
    assert all(r.result.status == "ok" for r in runs)
    assert delays.count("start") == 2
    assert elapsed < 0.15


@pytest.mark.asyncio
async def test_non_main_capability_not_capable() -> None:
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))
    runs = await run_delegate_directives(
        user_id="u1",
        turn_id="t1",
        directives=[
            DelegateDirective(
                capability="research",
                goal="deep",
                payload={"tool": "web_search", "args": {"query": "x"}},
            )
        ],
        runner=runner,
    )
    assert runs[0].result.status == "not_capable"
