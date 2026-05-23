from __future__ import annotations

from server.engine.prompt import SubPromptContext, build_sub_prompt


def test_sub_prompt_includes_warm_profile() -> None:
    prompt = build_sub_prompt(
        SubPromptContext(
            capability="research",
            task_id="t-1",
            goal="AI chips",
            payload={},
            warm_profile="User profile:\nname: Alex",
        )
    )
    assert "Alex" in prompt
    assert "deep_search" in prompt or "web_search" in prompt
