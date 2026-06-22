from __future__ import annotations

from server.engine.prompt import MainPromptContext, build_main_prompt


def test_build_main_prompt_is_single_unified_system_prompt() -> None:
    prompt = build_main_prompt(MainPromptContext(user_text="hi"))
    assert "You are Vayumi" in prompt
    assert "[SEARCH" in prompt
    assert "Greeting:" in prompt
    assert "[REMEMBER" in prompt
    assert "Session context" in prompt or "User: hi" in prompt
