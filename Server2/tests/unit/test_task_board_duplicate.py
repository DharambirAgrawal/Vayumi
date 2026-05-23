from __future__ import annotations

from server.orchestrator.task_board import TaskBoard


def test_find_running_same_goal() -> None:
    board = TaskBoard(user_id="u1")
    board.register_task(
        task_id="t1",
        capability="research",
        goal="in-depth Nepal news",
        payload={"tool": "deep_search"},
    )
    found = board.find_running("research", "in-depth Nepal news")
    assert found is not None
    assert found.task_id == "t1"


def test_format_completed_injection() -> None:
    board = TaskBoard(user_id="u1")
    row = board.register_task(
        task_id="t1",
        capability="research",
        goal="Nepal",
        payload={},
    )
    from server.subagents.report import report

    board.upsert_from_signal(
        report("t1", "DONE", "Avalanche and weather details from articles.")
    )
    block = board.format_completed_injection("tell me about Nepal")
    assert "BACKGROUND_TASK_DONE" in block
    assert "Avalanche" in block

    spacex_only = board.format_completed_injection(
        "What did you find on SpaceX Starship launch"
    )
    assert "quantum" not in spacex_only.lower() or "No completed" in spacex_only
