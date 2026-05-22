from __future__ import annotations

import pytest

from server.orchestrator.directives import (
    RecallDirective,
    RememberDirective,
    filter_profile_directives,
    format_recall_results,
    parse_directives,
    strip_directives,
)


def test_parse_remember_directive() -> None:
    text = '[REMEMBER key=name value="Alex" source="user_intent"]'
    directives = parse_directives(text)
    assert len(directives) == 1
    assert isinstance(directives[0], RememberDirective)
    assert directives[0].key == "name"
    assert directives[0].value == "Alex"
    assert directives[0].source == "user_intent"


def test_parse_recall_and_chain_directives() -> None:
    text = "[RECALL key=email.work]\n[RECALL chain key=email.work]"
    directives = parse_directives(text)
    kinds = {(type(d), getattr(d, "chain", False)) for d in directives}
    assert (RecallDirective, False) in kinds
    assert (RecallDirective, True) in kinds


def test_strip_directives_removes_blocks() -> None:
    raw = 'Sure. [REMEMBER key=name value="Alex" source="user_intent"] Done.'
    assert strip_directives(raw) == "Sure.  Done."


def test_filter_profile_directives_drops_invented_keys() -> None:
    parsed = parse_directives(
        "[RECALL chain key=story_topic]\n"
        '[REMEMBER key=preferences.voice value="soft" source="user_intent"]'
    )
    filtered = filter_profile_directives(parsed)
    assert len(filtered) == 1
    assert filtered[0].key == "preferences.voice"


def test_format_recall_results() -> None:
    from server.orchestrator.directives import RecallResult

    block = format_recall_results(
        [RecallResult(key="name", chain=False, payload='"Alex"')]
    )
    assert "RECALL_RESULT" in block
    assert "Alex" in block


@pytest.mark.asyncio
async def test_execute_remember_calls_set_fact(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.orchestrator import directives as mod

    calls: list[tuple[str, str, object, str]] = []

    async def fake_set_fact(
        user_id: str, key: str, value: object, source: str, **_: object
    ) -> None:
        calls.append((user_id, key, value, source))

    monkeypatch.setattr(mod.facts, "set_fact", fake_set_fact)

    await mod.execute_directives(
        "u1",
        [RememberDirective(key="name", value="Alex", source="user_intent")],
    )
    assert calls == [("u1", "name", "Alex", "user_intent")]
