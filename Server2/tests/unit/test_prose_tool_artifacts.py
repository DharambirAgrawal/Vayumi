from __future__ import annotations

from server.orchestrator.prose import strip_tool_artifacts


def test_strip_tavily_meta_and_numbered_snippets() -> None:
    raw = (
        "Okay, let's check the price!\n"
        "8 result(s) from tavily\n"
        "1. BTC USD — Bitcoin Price — The current price is 61,213 USD\n"
        "2. Bitcoin price today — live price is $61274\n"
        "Bitcoin is around $61,213 today."
    )
    cleaned = strip_tool_artifacts(raw)
    assert "tavily" not in cleaned.lower()
    assert "1. BTC" not in cleaned
    assert "61,213 today" in cleaned


def test_strip_tool_search_meta() -> None:
    raw = "I can find a story. Found 0 tool(s) for 'bedtime stories'!"
    cleaned = strip_tool_artifacts(raw)
    assert "Found 0 tool" not in cleaned
    assert "find a story" in cleaned
