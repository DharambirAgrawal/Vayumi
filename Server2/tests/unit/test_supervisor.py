from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from server.engine.pool import CompletionRequest, EnginePool
from server.orchestrator.supervisor import Supervisor


class _RecallThenAnswerClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self._pass = 0

    def stream_completion(
        self,
        *,
        base_url: str,
        slot_id: int,
        request: CompletionRequest,
    ) -> AsyncIterator[str]:
        return self._stream(base_url, slot_id, request)

    async def _stream(
        self,
        base_url: str,
        slot_id: int,
        request: CompletionRequest,
    ) -> AsyncIterator[str]:
        self.prompts.append(request.prompt)
        if self._pass == 0:
            self._pass += 1
            yield "[RECALL key=name]"
            return
        yield "Your name is Alex."


@pytest.mark.asyncio
async def test_supervisor_follow_up_on_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.orchestrator import supervisor as sup_mod

    async def noop(*args: object, **kwargs: object) -> None:
        return None

    async def fake_warm(user_id: str) -> str:
        return "Known profile facts:\n- name: Alex"

    async def fake_history(session_id: str, limit: int = 8) -> list:
        return []

    async def fake_summary(session_id: str) -> str:
        return ""

    async def fake_append(*args: object, **kwargs: object) -> object:
        from datetime import datetime, timezone

        from server.memory.session import TurnRecord

        return TurnRecord(
            id="t1",
            session_id="s1",
            user_id="u1",
            role="user",
            text="hi",
            created_at=datetime.now(timezone.utc),
        )

    async def fake_load(*args: object, **kwargs: object) -> object:
        from datetime import datetime, timezone

        from server.memory.session import SessionState

        return SessionState(
            id="s1",
            user_id="u1",
            client_meta={},
            compressed_summary=None,
            created_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )

    async def fake_execute(user_id: str, directives: list) -> list:
        from server.orchestrator.directives import RecallResult

        return [RecallResult(key="name", chain=False, payload='"Alex"')]

    monkeypatch.setattr(sup_mod, "build_warm_profile", fake_warm)
    monkeypatch.setattr(sup_mod, "recent_turns", fake_history)
    monkeypatch.setattr(sup_mod, "compressed_history", fake_summary)
    monkeypatch.setattr(sup_mod, "append_turn", fake_append)
    monkeypatch.setattr(sup_mod, "load_or_create_session", fake_load)
    monkeypatch.setattr(sup_mod, "execute_directives", fake_execute)

    client = _RecallThenAnswerClient()
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=client,
    )
    pool.start()
    supervisor = Supervisor(user_id="u1", session_id="s1")
    supervisor._ready = True

    try:
        output = await supervisor.run_turn("What is my name?", engine_pool=pool)
    finally:
        await pool.close()

    assert output.assistant_text == "Your name is Alex."
    assert len(client.prompts) == 2
    assert "RECALL_RESULT" in client.prompts[1]
