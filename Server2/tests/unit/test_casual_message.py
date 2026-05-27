from __future__ import annotations

from server.engine.prompt import MainPromptContext, build_main_prompt
from server.orchestrator.supervisor import _is_casual_message


def test_is_casual_message_recognizes_greetings() -> None:
    assert _is_casual_message("hey")
    assert _is_casual_message("Hey!")
    assert _is_casual_message("how are you")
    assert _is_casual_message("how r u")
    assert not _is_casual_message("what is the weather in Boston today")


def test_build_main_prompt_can_omit_tools_block() -> None:
    full = build_main_prompt(MainPromptContext(user_text="hi"), include_tools=True)
    core = build_main_prompt(MainPromptContext(user_text="hi"), include_tools=False)
    assert len(full) > len(core)
    assert "web_search" in full
    assert "web_search" not in core
