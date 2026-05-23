from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from server.config import Settings
from server.engine.pool import CompletionRequest, EnginePool
from server.orchestrator.signal_bus import SignalBus
from server.orchestrator.task_board import TaskBoard
from server.subagents.worker import SubAgentWorker
from server.tools import build_tool_registry, build_tool_runner


class _ReportThenDoneClient:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

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
        line = self._lines.pop(0) if self._lines else ""
        yield line


@pytest.mark.asyncio
async def test_worker_reports_step_and_done() -> None:
    step = '[REPORT kind=STEP summary="gathering sources" payload={}]'
    done = '[REPORT kind=DONE summary="research complete" payload={}]'
    client = _ReportThenDoneClient([step, done])
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=client,
    )
    pool.start()
    board = TaskBoard(user_id="u1")
    events: list[tuple[str, str, str]] = []

    async def on_event(kind: str, task_id: str, summary: str) -> None:
        events.append((kind, task_id, summary))

    bus = SignalBus(user_id="u1", task_board=board, on_event=on_event, persist=False)
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    registry = build_tool_registry(settings)
    runner = build_tool_runner(registry)

    try:
        slot_id = await pool.assign_slot("task-1", "subagent")
        worker = SubAgentWorker(
            task_id="task-1",
            user_id="u1",
            session_id="s1",
            capability="research",
            goal="AI chips",
            payload={},
            engine_pool=pool,
            tool_runner=runner,
            signal_bus=bus,
            slot_id=slot_id,
        )
        await worker.run()
    finally:
        await pool.close()

    assert any(e[0] == "task_step" for e in events)
    assert events[-1][0] == "task_done"
    assert pool.slot_for_task("task-1") is None
    row = board.get("task-1")
    assert row is not None
    assert row.status == "done"


@pytest.mark.asyncio
async def test_worker_needs_info_pauses() -> None:
    needs = (
        '[REPORT kind=NEEDS_INFO summary="need scope" '
        'payload={"question":"2024 only or all-time?"}]'
    )
    client = _ReportThenDoneClient([needs])
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=client,
    )
    pool.start()
    board = TaskBoard(user_id="u1")
    bus = SignalBus(user_id="u1", task_board=board, persist=False)
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    runner = build_tool_runner(build_tool_registry(settings))

    try:
        slot_id = await pool.assign_slot("task-2", "subagent")
        worker = SubAgentWorker(
            task_id="task-2",
            user_id="u1",
            session_id="s1",
            capability="research",
            goal="scope",
            payload={},
            engine_pool=pool,
            tool_runner=runner,
            signal_bus=bus,
            slot_id=slot_id,
        )
        await worker.run()
        row = board.get("task-2")
        assert row is not None
        assert row.status == "paused"
        assert "2024" in (row.waiting_for or "")
    finally:
        await pool.close()
