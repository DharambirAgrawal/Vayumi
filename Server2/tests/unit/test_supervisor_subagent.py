from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from server.config import Settings
from server.engine.pool import CompletionRequest, EnginePool
from server.orchestrator.supervisor import Supervisor
from server.tools import build_tool_registry, build_tool_runner


class _MainSpawnClient:
    def __init__(self) -> None:
        self._pass = 0
        self.prompts: list[str] = []

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
                'Starting research.\n[DELEGATE capability=research goal="AI chips" '
                'payload={}]'
            )
            return
        yield "I've kicked off background research on AI chips."


class _SubagentFastClient:
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
        yield '[REPORT kind=DONE summary="chips report ready" payload={}]'


class _SubagentSlowClient:
    def __init__(self) -> None:
        self._blocked = asyncio.Event()

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
        await self._blocked.wait()
        yield '[REPORT kind=DONE summary="late" payload={}]'


class _LeakyPlanClient:
    def __init__(self) -> None:
        self._pass = 0
        self.prompts: list[str] = []

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
        if "Worker:" in request.prompt:
            yield '[REPORT kind=DONE summary="clean research summary" payload={}]'
            return
        if self._pass == 0:
            self._pass += 1
            yield (
                "I'm on it.\n"
                "User: What's the latest on Tesla?\n"
                "Vayumi:\n"
                '[DELEGATE capability=research goal="AI chips" payload={}]'
            )
            return
        yield "Background research is running."


class _SocialObservationClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

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
        yield "Yeah, he sounds like someone with a good heart."


@pytest.fixture
def patched_memory(monkeypatch: pytest.MonkeyPatch):
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
            text="go",
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
async def test_spawn_research_non_blocking(patched_memory: None) -> None:
    main_client = _MainSpawnClient()
    sub_client = _SubagentFastClient()

    class _RouterClient:
        def stream_completion(self, *, base_url, slot_id, request):
            if "Worker:" in request.prompt:
                return sub_client.stream_completion(
                    base_url=base_url, slot_id=slot_id, request=request
                )
            return main_client.stream_completion(
                base_url=base_url, slot_id=slot_id, request=request
            )

    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=_RouterClient(),
    )
    pool.start()
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))
    supervisor = Supervisor(user_id="u1", session_id="s1")
    supervisor._ready = True
    events: list[tuple[str, str, str]] = []

    async def on_event(kind: str, task_id: str, summary: str) -> None:
        events.append((kind, task_id, summary))

    try:
        output = await supervisor.run_turn(
            "research AI chips in depth",
            engine_pool=pool,
            tool_runner=runner,
            on_task_event=on_event,
        )
        text = output.assistant_text.lower()
        assert "background" in text or "research" in text
        if supervisor._worker_tasks:
            await asyncio.wait_for(
                asyncio.gather(*supervisor._worker_tasks.values()),
                timeout=5.0,
            )
        assert any(e[0] == "task_done" for e in events)
    finally:
        for task in list(supervisor._worker_tasks.values()):
            if not task.done():
                task.cancel()
        await pool.close()


@pytest.mark.asyncio
async def test_cancel_task_frees_slot(patched_memory: None) -> None:
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=_SubagentSlowClient(),  # blocks until process exit
    )
    pool.start()
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))
    supervisor = Supervisor(user_id="u1", session_id="s1")
    supervisor._ready = True

    async def wait_for_slot(task_id: str) -> int:
        while True:
            slot_id = pool.slot_for_task(task_id)
            if slot_id is not None:
                return slot_id
            await asyncio.sleep(0.01)

    try:
        task_id = await supervisor.spawn_subagent(
            "research",
            "long job",
            {},
            engine_pool=pool,
            tool_runner=runner,
        )
        assert await asyncio.wait_for(wait_for_slot(task_id), timeout=1.0) is not None
        ok = await supervisor.cancel_task(task_id, engine_pool=pool)
        assert ok is True
        assert pool.slot_for_task(task_id) is None
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_step_events_without_main_tts(patched_memory: None) -> None:
    """Path A: STEP signals do not require Main on_token during worker run."""
    board_events: list[str] = []
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=_SubagentFastClient(),
    )
    pool.start()
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))
    supervisor = Supervisor(user_id="u1", session_id="s1")
    supervisor._ready = True

    async def on_task(kind: str, task_id: str, summary: str) -> None:
        board_events.append(kind)

    tokens: list[str] = []

    async def on_token(tok: str) -> None:
        tokens.append(tok)

    try:
        supervisor.attach_task_events(on_task)
        task_id = await supervisor.spawn_subagent(
            "research",
            "progress only",
            {},
            engine_pool=pool,
            tool_runner=runner,
        )
        await asyncio.wait_for(supervisor._worker_tasks[task_id], timeout=5.0)
        assert "task_done" in board_events
        assert tokens == []
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_plan_pass_tokens_are_not_delivered(patched_memory: None) -> None:
    client = _LeakyPlanClient()
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=client,
    )
    pool.start()
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))
    supervisor = Supervisor(user_id="u1", session_id="s1")
    supervisor._ready = True
    tokens: list[str] = []
    status: list[str] = []

    async def on_token(tok: str) -> None:
        tokens.append(tok)

    async def on_status(text: str) -> None:
        status.append(text)

    try:
        output = await supervisor.run_turn(
            "research AI chips in depth",
            engine_pool=pool,
            tool_runner=runner,
            on_token=on_token,
            on_status_caption=on_status,
        )
        delivered = "".join(tokens)
        assert "Tesla" not in delivered
        assert "User:" not in delivered
        assert "Background research is running" in delivered
        assert output.assistant_text == "Background research is running."
        assert status == ["I'm on it."]
    finally:
        for task in list(supervisor._worker_tasks.values()):
            if not task.done():
                task.cancel()
        await pool.close()


@pytest.mark.asyncio
async def test_short_social_observation_does_not_spawn_tools(
    patched_memory: None,
) -> None:
    client = _SocialObservationClient()
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=client,
    )
    pool.start()
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))
    supervisor = Supervisor(user_id="u1", session_id="s1")
    supervisor._ready = True
    events: list[tuple[str, str, str]] = []

    async def on_event(kind: str, task_id: str, summary: str) -> None:
        events.append((kind, task_id, summary))

    try:
        output = await supervisor.run_turn(
            "He's a good guy.",
            engine_pool=pool,
            tool_runner=runner,
            on_task_event=on_event,
        )
        assert "good heart" in output.assistant_text
        assert events == []
        assert supervisor._worker_tasks == {}
        assert "Tool catalog" not in client.prompts[0]
    finally:
        await pool.close()
