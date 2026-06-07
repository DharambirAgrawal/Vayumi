from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from server.memory.session import (
    TurnRecord,
    estimate_history_tokens,
    estimate_text_tokens,
    turns_for_summarization,
)


def test_estimate_text_tokens() -> None:
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens("abcd") == 1
    assert estimate_text_tokens("a" * 40) == 10


@pytest.mark.asyncio
async def test_estimate_history_tokens_includes_summary_and_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.memory import session as mod

    class _Conn:
        async def fetch(self, query: str, *args: object) -> list[dict[str, Any]]:
            if "SELECT text FROM turns" in query:
                return [{"text": "x" * 400}]
            return []

        async def fetchrow(self, query: str, *args: object) -> dict[str, Any]:
            return {"compressed_summary": "y" * 400}

    class _Acquire:
        async def __aenter__(self) -> _Conn:
            return _Conn()

        async def __aexit__(self, *args: object) -> None:
            return None

    class _Pool:
        def acquire(self) -> _Acquire:
            return _Acquire()

    monkeypatch.setattr(mod, "get_pool", lambda: _Pool())
    total = await estimate_history_tokens("s1")
    assert total == estimate_text_tokens("y" * 400) + estimate_text_tokens("x" * 400)


@pytest.mark.asyncio
async def test_turns_for_summarization_keeps_recent_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.memory import session as mod

    now = datetime.now(timezone.utc)
    turns = [
        TurnRecord(
            id=f"id-{idx}",
            session_id="s1",
            user_id="u1",
            role="user",
            text=f"t{idx}",
            created_at=now,
        )
        for idx in range(5)
    ]

    async def fake_all(session_id: str) -> list[TurnRecord]:
        return turns

    monkeypatch.setattr(mod, "all_turns_ordered", fake_all)
    old = await turns_for_summarization("s1", keep_recent=2)
    assert len(old) == 3
    assert old[0].id == "id-0"
    assert old[-1].id == "id-2"
