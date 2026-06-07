from __future__ import annotations

from server.orchestrator.directives import DelegateDirective
from server.orchestrator.tool_dispatch import (
    DelegateRun,
    build_follow_up_context,
    format_subagent_spawn_block,
)
from server.tools.registry import ToolResult


def test_multi_part_context_includes_immediate_and_background() -> None:
    run = DelegateRun(
        directive=DelegateDirective(
            capability="main",
            goal="Nepal news",
            payload={"tool": "web_search", "args": {"query": "Nepal"}},
        ),
        tool_name="web_search",
        result=ToolResult(status="ok", summary="2 results", data={"results": []}),
    )
    ctx = build_follow_up_context(
        spawn_blocks=[format_subagent_spawn_block("x", "research", "Tesla deep")],
        delegate_runs=[run],
    )
    assert "Immediate result" in ctx
    assert "Nepal news" in ctx
    assert "Background research started" in ctx
    assert "SUBAGENT_SPAWN" not in ctx
    assert "multiple things" in ctx.lower() or "multiple" in ctx.lower()
