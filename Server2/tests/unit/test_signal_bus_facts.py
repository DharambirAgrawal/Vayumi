from __future__ import annotations

import pytest

from server.orchestrator.signal_bus import SignalBus
from server.orchestrator.task_board import TaskBoard
from server.subagents.report import report


@pytest.mark.asyncio
async def test_signal_bus_done_schedules_fact_extraction_in_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[tuple[str, str, object]] = []

    def fake_schedule(
        *,
        task_id: str,
        user_id: str,
        facts_payload: object,
    ) -> None:
        scheduled.append((task_id, user_id, facts_payload))

    import server.orchestrator.signal_bus as bus_mod

    monkeypatch.setattr(bus_mod, "schedule_task_fact_extraction", fake_schedule)

    board = TaskBoard(user_id="u1")
    bus = SignalBus(user_id="u1", task_board=board, persist=False)
    signal = report(
        "task-abc",
        "DONE",
        "Research complete",
        payload={
            "facts_to_persist": [
                {"key": "integrations.calendar", "value": ["Cron"], "confidence": 0.9}
            ]
        },
    )
    await bus.publish(signal)
    assert scheduled == [
        (
            "task-abc",
            "u1",
            [{"key": "integrations.calendar", "value": ["Cron"], "confidence": 0.9}],
        )
    ]
