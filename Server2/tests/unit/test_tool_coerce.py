from __future__ import annotations

from server.orchestrator.directives import (
    DelegateDirective,
    strip_directives,
    strip_internal_tool_blocks,
)
from server.orchestrator.tool_dispatch import coerce_delegates_for_live_web
from server.orchestrator.tool_intent import suggest_web_search_query


def test_suggest_nvidia_stock_query() -> None:
    q = suggest_web_search_query(
        "what going on currently in the interned and nvdi stock"
    )
    assert q is not None


def test_coerce_tool_search_to_web_search() -> None:
    directives = [
        DelegateDirective(
            capability="main",
            goal="find tools",
            payload={
                "tool": "tool_search",
                "args": {"query": "news nvidia"},
            },
        )
    ]
    coerced = coerce_delegates_for_live_web(
        "what going on with nvidia stock", directives
    )
    assert len(coerced) == 1
    assert coerced[0].payload["tool"] == "web_search"


def test_strip_tool_result_from_visible_text() -> None:
    raw = (
        "Here is the news.\n"
        "[TOOL_RESULT tool=tool_search status=ok] Found 4 tool(s) for 'x'\n"
        "NVIDIA moved today."
    )
    clean = strip_directives(raw)
    assert "TOOL_RESULT" not in clean
    assert "Found 4 tool" not in clean
    assert "NVIDIA moved" in clean


def test_strip_internal_tool_blocks() -> None:
    text = "[TOOL_RESULT tool=web_search status=ok] 3 result(s)\n1. Title — snippet"
    assert "TOOL_RESULT" not in strip_internal_tool_blocks(text)
