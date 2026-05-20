from __future__ import annotations

from server.engine.prompt import MainPromptContext, build_main_prompt


def test_build_main_prompt_includes_system_and_user_text() -> None:
    prompt = build_main_prompt(MainPromptContext(user_text=" hello Vayumi "))

    assert "You are Vayumi" in prompt
    assert "User: hello Vayumi" in prompt
    assert prompt.rstrip().endswith("Vayumi:")
    assert "warm profile" in prompt.lower() or "You are Vayumi" in prompt


def test_build_main_prompt_includes_warm_and_history() -> None:
    prompt = build_main_prompt(
        MainPromptContext(
            user_text="What is my name?",
            warm_profile="Known profile facts:\n- name: Alex",
            history_lines=["user: hi", "assistant: hello"],
            recall_context="[RECALL_RESULT key=name] \"Alex\"",
        )
    )

    assert "name: Alex" in prompt
    assert "user: hi" in prompt
    assert "RECALL_RESULT" in prompt
    assert prompt.endswith("Vayumi:\n")
