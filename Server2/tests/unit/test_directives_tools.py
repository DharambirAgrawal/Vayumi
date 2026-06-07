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


def test_strip_internal_background_markers() -> None:
    raw = (
        "Okay.\n"
        '[SUBAGENT_SPAWN task_id=t1 capability=research goal="good guy"] '
        "(background research worker — results arrive later via notification)\n"
        '[BACKGROUND_TASK_DONE task_id=t1 capability=research goal="good guy"]\n'
        '[PROACTIVE_SIGNAL kind=DONE task_id=t1 capability=research goal="good guy"]\n'
        "User: What's the latest on Tesla?\n"
        "Vayumi:\n"
        "Done."
    )
    cleaned = strip_directives(raw)
    assert "SUBAGENT_SPAWN" not in cleaned
    assert "BACKGROUND_TASK_DONE" not in cleaned
    assert "PROACTIVE_SIGNAL" not in cleaned
    assert "User:" not in cleaned
    assert "Vayumi:" not in cleaned
    assert "Tesla" not in cleaned
    assert "Done." in cleaned
