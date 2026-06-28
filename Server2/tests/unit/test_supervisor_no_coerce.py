from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from server.config import Settings
from server.engine.pool import CompletionRequest, EnginePool
from server.orchestrator.supervisor import Supervisor
from server.tools import build_tool_registry, build_tool_runner


class _NoDelegateClient:
    """Model emits no DELEGATE — server must not auto-run tools."""

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
        del base_url, slot_id, request
        yield "I don't have access to real-time news. Would you like me to search?"


@pytest.mark.asyncio
async def test_supervisor_does_not_auto_web_search_without_delegate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            text="news",
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

    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    registry = build_tool_registry(settings)
    runner = build_tool_runner(registry)

    client = _NoDelegateClient()
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=client,
    )
    pool.start()
    events: list[str] = []

    async def on_event(kind: str, task_id: str, summary: str) -> None:
        del task_id, summary
        events.append(kind)

    supervisor = Supervisor(user_id="u1", session_id="s1")
    supervisor._ready = True
    try:
        await supervisor.run_turn(
            "What do you think about friendship in general",
            engine_pool=pool,
            tool_runner=runner,
            on_tool_event=on_event,
        )
    finally:
        await pool.close()

    assert "tool_started" not in events
    assert "tool_done" not in events


@pytest.mark.asyncio
async def test_ack_only_does_not_force_web_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.engine.pool import ChatCompletionResult
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

    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    registry = build_tool_registry(settings)
    runner = build_tool_runner(registry)

    class _AckOnlyClient(_NoDelegateClient):
        async def complete_chat(
            self,
            *,
            base_url: str,
            slot_id: int | None,
            request: CompletionRequest,
        ) -> ChatCompletionResult:
            del base_url, slot_id, request
            return ChatCompletionResult(
                content="Let me check that for you.",
                tool_calls=[],
            )

    client = _AckOnlyClient()
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=client,
    )
    pool.start()
    events: list[str] = []

    async def on_event(kind: str, task_id: str, summary: str) -> None:
        del task_id, summary
        events.append(kind)

    async def fake_web_search(
        *,
        user_id: str,
        query: str,
        max_results: int = 5,
        tavily_api_key=None,
    ):
        del user_id, query, max_results, tavily_api_key
        from server.tools.registry import ToolResult

        return ToolResult(
            status="ok",
            summary="ok",
            data={
                "results": [
                    {"snippet": "NVIDIA (NVDA) last traded at $120.50."}
                ]
            },
        )

    entry = registry.get("web_search")
    assert entry is not None
    entry.fn = fake_web_search  # type: ignore[method-assign]

    supervisor = Supervisor(user_id="u1", session_id="s1")
    supervisor._ready = True
    try:
        out = await supervisor.run_turn(
            "what is the nvidia stock price",
            engine_pool=pool,
            tool_runner=runner,
            on_tool_event=on_event,
        )
    finally:
        await pool.close()

    # The model acknowledged but emitted no tool_call. We trust it — the old
    # regex that force-ran a web_search behind the model's back is gone.
    assert "tool_started" not in events
    assert "tool_done" not in events
    assert out.assistant_text.strip() != ""
    assert "[web_search" not in out.assistant_text
