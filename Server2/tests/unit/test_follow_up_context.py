from __future__ import annotations

from server.orchestrator.tool_dispatch import (
    build_follow_up_context,
    format_subagent_spawn_block,
)


def test_spawn_only_context_tells_user_work_started() -> None:
    ctx = build_follow_up_context(
        spawn_blocks=[format_subagent_spawn_block("x", "research", "Tesla deep")],
    )
    assert "Background research started" in ctx
    assert "SUBAGENT_SPAWN" not in ctx
    assert "No [DELEGATE]" in ctx


def test_recall_only_context_includes_facts() -> None:
    ctx = build_follow_up_context(recall_block="address: 1 Main St")
    assert "1 Main St" in ctx
    assert "recalled facts" in ctx.lower()


def test_spawn_and_recall_combined() -> None:
    ctx = build_follow_up_context(
        recall_block="name: Sam",
        spawn_blocks=[format_subagent_spawn_block("x", "research", "chips")],
    )
    assert "Sam" in ctx
    assert "Background research started" in ctx
