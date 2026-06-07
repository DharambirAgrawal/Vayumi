from __future__ import annotations

from server.orchestrator.task_board import TaskBoard


def test_continue_injects_most_recent_completed_task() -> None:
    board = TaskBoard(user_id="u1")
    row = board.register_task(
        task_id="t1",
        capability="research",
        goal="deep research on the moon",
    )
    row.status = "done"
    row.result_summary = "The Moon formed 4.5 billion years ago."
    board._finalize(row)
    injection = board.format_completed_injection("yes continue")
    assert "Moon formed" in injection
    assert "BACKGROUND_TASK_DONE" in injection
