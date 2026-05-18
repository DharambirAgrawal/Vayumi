from __future__ import annotations

from server.engine.prompt import MainPromptContext, build_main_prompt


def test_build_main_prompt_includes_system_and_user_text() -> None:
    prompt = build_main_prompt(MainPromptContext(user_text=" hello Vayumi "))

    assert "You are Vayumi" in prompt
    assert "User: hello Vayumi" in prompt
    assert prompt.endswith("Vayumi:")
    assert "tools" in prompt.lower()
