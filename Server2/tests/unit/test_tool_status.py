from __future__ import annotations

from server.orchestrator.directives import DelegateDirective
from server.orchestrator.tool_dispatch import tool_status_message


def test_tool_status_web_search() -> None:
    msg = tool_status_message(
        "What is latest going on in the news",
        [
            DelegateDirective(
                capability="main",
                goal="news",
                payload={
                    "tool": "web_search",
                    "args": {"query": "world news today"},
                },
            )
        ],
    )
    assert "Searching the web" in msg
    assert "world news" in msg


def test_streaming_tts_strips_delegate_from_sentence() -> None:
    from server.orchestrator.directives import strip_directives

    raw = (
        '[DELEGATE capability=main goal="x" payload={"tool":"web_search","args":{"query":"q"}}]\n'
        "Here is the answer."
    )
    assert "DELEGATE" not in strip_directives(raw)
    assert "Here is the answer" in strip_directives(raw)
