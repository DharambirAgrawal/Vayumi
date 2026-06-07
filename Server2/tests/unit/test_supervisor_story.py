from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from server.config import Settings
from server.engine.pool import CompletionRequest, EnginePool
from server.orchestrator.supervisor import Supervisor
from server.tools import build_tool_registry, build_tool_runner


class _StoryClient:
    def __init__(self) -> None:
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
        self.requests.append(request)
        yield (
            "Once upon a time there was a fox. "
            "The fox ran through the valley. "
            "And everyone cheered at the end."
        )


class _ThankYouStoryClient:
    def __init__(self) -> None:
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
        self.requests.append(request)
        yield "You're welcome! Here is the rest of the story about the brave fox."


async def _patch_memory(monkeypatch: pytest.MonkeyPatch) -> None:
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
            text="x",
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
async def test_story_uses_full_answer_budget_in_one_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _patch_memory(monkeypatch)

    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))
    client = _StoryClient()
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=client,
    )
    pool.start()

    supervisor = Supervisor(user_id="u1", session_id="s1")
    supervisor._ready = True
    try:
        output = await supervisor.run_turn(
            "tell me a nice night time story",
            engine_pool=pool,
            tool_runner=runner,
        )
    finally:
        await pool.close()

    assert len(client.requests) == 1
    assert client.requests[0].max_tokens == 1024
    assert "fox" in output.assistant_text.lower()
    assert "DELEGATE" not in output.assistant_text


@pytest.mark.asyncio
async def test_thank_you_uses_answer_token_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _patch_memory(monkeypatch)

    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))
    client = _ThankYouStoryClient()
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=client,
    )
    pool.start()

    supervisor = Supervisor(user_id="u1", session_id="s1")
    supervisor._ready = True
    try:
        await supervisor.run_turn(
            "Thank you.",
            engine_pool=pool,
            tool_runner=runner,
            allow_delegates=False,
        )
    finally:
        await pool.close()

    assert len(client.requests) == 1
    assert client.requests[0].max_tokens == 1024
