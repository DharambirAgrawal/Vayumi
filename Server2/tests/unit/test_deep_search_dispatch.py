from __future__ import annotations

import pytest

from server.config import Settings
from server.orchestrator.directives import DelegateDirective
from server.orchestrator.tool_dispatch import run_subagent_tool_delegate
from server.tools import build_tool_registry, build_tool_runner
from server.tools.registry import ToolCall


@pytest.mark.asyncio
async def test_main_cannot_run_deep_search() -> None:
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))
    run = await runner.execute(
        "t1",
        ToolCall(name="deep_search", args={"query": "ai"}, capability="main"),
        user_id="u1",
    )
    assert run.status == "not_capable"


@pytest.mark.asyncio
async def test_research_deep_search_registered() -> None:
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    registry = build_tool_registry(settings)
    entry = registry.get("deep_search", "research")
    assert entry is not None
    assert entry.capability == "research"
    assert entry.cost_hint == "heavy"


@pytest.mark.asyncio
async def test_research_delegate_deep_search_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.tools import deep_search as ds_mod

    async def _fake_deep_search(**kwargs: object) -> object:
        from server.tools.registry import ToolResult

        del kwargs
        return ToolResult(status="ok", summary="1 full read", data={"articles": []})

    monkeypatch.setattr(ds_mod, "deep_search", _fake_deep_search)

    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))
    directive = DelegateDirective(
        capability="research",
        goal="in depth",
        payload={"tool": "deep_search", "args": {"query": "AI chips", "max_urls": 2}},
    )
    run = await run_subagent_tool_delegate(
        user_id="u1",
        task_id="task-1",
        directive=directive,
        runner=runner,
    )
    assert run.tool_name == "deep_search"
    assert run.result.status == "ok"
