from __future__ import annotations

from server.config import Settings
from server.engine.prompt import SubPromptContext, build_subagent_prompt
from server.subagents.capabilities import load_capability, render_tool_cards_for_bundle
from server.tools import build_tool_registry


def test_sub_prompt_includes_warm_profile_and_tool_cards() -> None:
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    registry = build_tool_registry(settings)
    bundle = load_capability("research")
    tool_cards = render_tool_cards_for_bundle(registry, bundle)
    prompt = build_subagent_prompt(
        bundle,
        SubPromptContext(
            capability="research",
            task_id="t-1",
            goal="AI chips",
            payload={},
            warm_profile="User profile:\nname: Alex",
            tool_context=tool_cards,
        ),
    )
    assert "Alex" in prompt
    assert "deep_search" in prompt
    assert "summarize_url" in prompt
    assert "fetch_url" not in prompt
