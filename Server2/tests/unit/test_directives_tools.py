from __future__ import annotations

from server.orchestrator.directives import (
    parse_delegate_directives,
    strip_directives,
)


def test_parse_delegate_main_tool() -> None:
    text = (
        'Looking that up.\n'
        '[DELEGATE capability=main goal="search news" '
        'payload={"tool":"web_search","args":{"query":"latest AI news","max_results":3}}]'
    )
    directives = parse_delegate_directives(text)
    assert len(directives) == 1
    d = directives[0]
    assert d.capability == "main"
    assert d.goal == "search news"
    assert d.payload["tool"] == "web_search"
    assert d.payload["args"]["query"] == "latest AI news"


def test_parse_multiple_delegates_same_turn() -> None:
    main_block = (
        '[DELEGATE capability=main goal="a" '
        'payload={"tool":"tool_search","args":{"query":"web"}}]'
    )
    research_block = (
        '[DELEGATE capability=research goal="b" '
        'payload={"tool":"web_search","args":{"query":"x"}}]'
    )
    text = f"{main_block}\n{research_block}"
    directives = parse_delegate_directives(text)
    assert len(directives) == 2
    assert directives[0].capability == "main"
    assert directives[1].capability == "research"


def test_strip_delegate_removes_block() -> None:
    raw = (
        'Sure.\n[DELEGATE capability=main goal="g" '
        'payload={"tool":"memory_recall","args":{"key":"name"}}]\nDone.'
    )
    cleaned = strip_directives(raw)
    assert "DELEGATE" not in cleaned
    assert "Done." in cleaned
