from __future__ import annotations

import pytest

from server.orchestrator.signal_bus import SignalBus
from server.orchestrator.task_board import TaskBoard
from server.subagents.report import report


@pytest.mark.asyncio
async def test_publish_emits_task_event() -> None:
    board = TaskBoard(user_id="u1")
    events: list[tuple[str, str, str]] = []

    async def on_event(kind: str, task_id: str, summary: str) -> None:
        events.append((kind, task_id, summary))

    bus = SignalBus(user_id="u1", task_board=board, on_event=on_event, persist=False)
    await bus.publish_task_created(
        task_id="t1",
        capability="research",
        goal="test goal",
        payload={},
    )
    await bus.publish(report("t1", "STEP", "step one"))

    assert events[0][0] == "task_step"
    assert events[1][0] == "task_step"
    assert board.get("t1") is not None
    assert board.get("t1").latest_step == "step one"
