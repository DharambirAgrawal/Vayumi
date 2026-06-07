from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from server.engine.pool import CompletionRequest, EnginePool
from server.orchestrator.supervisor import Supervisor


class _ScriptedClient:
    def __init__(self, outputs: list[str | None]) -> None:
        self.outputs = outputs
        self.prompts: list[str] = []
        self.requests: list[CompletionRequest] = []

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
        del base_url, slot_id
        self.prompts.append(request.prompt)
        self.requests.append(request)
        output = self.outputs.pop(0)
        if output is None:
            if False:
                yield ""
            return
        yield output


@pytest.fixture
def patched_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.orchestrator import supervisor as sup_mod

    async def fake_warm(user_id: str) -> str:
        del user_id
        return ""

    async def fake_history(session_id: str, limit: int = 8) -> list:
        del session_id, limit
        return []

    async def fake_summary(session_id: str) -> str:
        del session_id
        return ""

    async def fake_append(*args: object, **kwargs: object) -> object:
        from datetime import datetime, timezone

        from server.memory.session import TurnRecord

        return TurnRecord(
            id="t1",
            session_id="s1",
            user_id="u1",
            role="user",
            text="hello",
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

    monkeypatch.setattr(sup_mod, "build_warm_profile", fake_warm)
    monkeypatch.setattr(sup_mod, "recent_turns", fake_history)
    monkeypatch.setattr(sup_mod, "compressed_history", fake_summary)
    monkeypatch.setattr(sup_mod, "append_turn", fake_append)
    monkeypatch.setattr(sup_mod, "load_or_create_session", fake_load)


@pytest.mark.asyncio
async def test_no_delegate_request_disables_cache_prompt(
    patched_memory: None,
) -> None:
    client = _ScriptedClient(["Hello there."])
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=2,
        completion_client=client,
    )
    pool.start()
    supervisor = Supervisor(user_id="u1", session_id="s1")
    supervisor._ready = True

    try:
        output = await supervisor.run_turn(
            "hello",
            engine_pool=pool,
            allow_delegates=False,
        )
    finally:
        await pool.close()

    assert output.assistant_text == "Hello there."
    assert len(client.requests) == 1
    assert client.requests[0].cache_prompt is False


@pytest.mark.asyncio
async def test_empty_response_retries_with_second_llm_pass(
    patched_memory: None,
) -> None:
    client = _ScriptedClient([None, "Hello there."])
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=2,
        completion_client=client,
    )
    pool.start()
    supervisor = Supervisor(user_id="u1", session_id="s1")
    supervisor._ready = True

    try:
        output = await supervisor.run_turn(
            "explain quantum dots briefly",
            engine_pool=pool,
            allow_delegates=False,
        )
    finally:
        await pool.close()

    assert output.assistant_text == "Hello there."
    assert len(client.prompts) == 2
    retry_blob = (
        json.dumps(client.prompts[1])
        if isinstance(client.prompts[1], list)
        else client.prompts[1]
    )
    assert "previous model pass returned no visible text" in retry_blob
    assert [request.cache_prompt for request in client.requests] == [False, False]
