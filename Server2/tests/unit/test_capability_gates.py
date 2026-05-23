from __future__ import annotations

import pytest

from server.config import Settings
from server.orchestrator.directives import DelegateDirective
from server.orchestrator.tool_dispatch import run_subagent_tool_delegate
from server.tools import build_tool_registry, build_tool_runner


@pytest.mark.asyncio
async def test_productivity_cannot_run_deep_search() -> None:
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))
    directive = DelegateDirective(
        capability="productivity",
        goal="research topic",
        payload={"tool": "deep_search", "args": {"query": "x"}},
    )
    run = await run_subagent_tool_delegate(
        user_id="u1",
        task_id="task-p1",
        directive=directive,
        runner=runner,
    )
    assert run.result.status == "not_capable"
    assert "bundle" in run.result.summary.lower()


@pytest.mark.asyncio
async def test_research_can_run_summarize_url_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake(**kwargs: object) -> object:
        from server.tools.registry import ToolResult

        del kwargs
        return ToolResult(status="ok", summary="article", data={"text": "body"})

    monkeypatch.setattr(
        "server.tools.summarize_url.summarize_url",
        _fake,
    )

    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))
    directive = DelegateDirective(
        capability="research",
        goal="read page",
        payload={
            "tool": "summarize_url",
            "args": {"url": "https://example.com/a"},
        },
    )
    run = await run_subagent_tool_delegate(
        user_id="u1",
        task_id="task-r1",
        directive=directive,
        runner=runner,
    )
    assert run.tool_name == "summarize_url"
    assert run.result.status == "ok"
