from __future__ import annotations

from server.orchestrator.tool_fallback import is_trivial_chat_followup


def test_trivial_chat_followup() -> None:
    assert is_trivial_chat_followup("?")
    assert is_trivial_chat_followup("!")
    assert is_trivial_chat_followup("")
    assert not is_trivial_chat_followup("what is nvidia stock price")
