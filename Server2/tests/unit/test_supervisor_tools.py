from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from server.config import Settings
from server.engine.pool import CompletionRequest, EnginePool
from server.orchestrator.supervisor import Supervisor
from server.tools import build_tool_registry, build_tool_runner


class _DelegateThenAnswerClient:
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
        del base_url, slot_id
        self.prompts.append(request.prompt)
        if self._pass == 0:
            self._pass += 1
            yield (
                'Searching now.\n[DELEGATE capability=main goal="news" '
                'payload={"tool":"web_search","args":{"query":"AI","max_results":2}}]'
            )
            return
        yield "Here are the top AI headlines from the search results."


@pytest.mark.asyncio
async def test_supervisor_main_tool_follow_up(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.orchestrator import supervisor as sup_mod

    async def noop(*args: object, **kwargs: object) -> None:
        return None

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
            text="search AI news",
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

    async def fake_web_search(
        *,
        user_id: str,
        query: str,
        max_results: int = 5,
        tavily_api_key=None,
    ):
        del user_id, tavily_api_key
        from server.tools.registry import ToolResult

        return ToolResult(
            status="ok",
            summary="2 results",
            data={
                "results": [
                    {"title": "AI Today", "url": "https://a", "snippet": "s1", "source": "tavily"},
                    {"title": "ML Weekly", "url": "https://b", "snippet": "s2", "source": "tavily"},
                ],
                "query": query,
                "backend": "tavily",
            },
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
    entry = registry.get("web_search")
    assert entry is not None
    entry.fn = fake_web_search  # type: ignore[method-assign]
    runner = build_tool_runner(registry)

    client = _DelegateThenAnswerClient()
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=client,
    )
    pool.start()
    events: list[tuple[str, str, str]] = []

    async def on_event(kind: str, task_id: str, summary: str) -> None:
        events.append((kind, task_id, summary))

    supervisor = Supervisor(user_id="u1", session_id="s1")
    supervisor._ready = True
    try:
        output = await supervisor.run_turn(
            "search for AI news",
            engine_pool=pool,
            tool_runner=runner,
            on_tool_event=on_event,
        )
    finally:
        await pool.close()

    assert "headlines" in output.assistant_text.lower() or "search" in output.assistant_text.lower()
    assert len(events) == 2
    assert events[0][0] == "tool_started"
    assert events[1][0] == "tool_done"
    assert len(client.prompts) == 2
    assert "TOOL_RESULT" in client.prompts[1]
