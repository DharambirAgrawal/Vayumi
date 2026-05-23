from __future__ import annotations

from server.orchestrator.task_board import TaskBoard
from server.subagents.report import report


def test_upsert_step_and_render() -> None:
    board = TaskBoard(user_id="u1")
    board.register_task(task_id="t1", capability="research", goal="AI chips")
    board.upsert_from_signal(report("t1", "STEP", "collecting sources"))
    rendered = board.render_for_main()
    assert "active_tasks" in rendered
    assert "collecting sources" in rendered
    snap = board.snapshot()
    assert snap["running"] == 1


def test_needs_info_pauses() -> None:
    board = TaskBoard(user_id="u1")
    board.register_task(task_id="t1", capability="research", goal="report")
    board.upsert_from_signal(
        report("t1", "NEEDS_INFO", "need input", {"question": "Focus on 2024?"})
    )
    row = board.get("t1")
    assert row is not None
    assert row.status == "paused"
    assert row.waiting_for == "Focus on 2024?"


def test_done_moves_to_completed() -> None:
    board = TaskBoard(user_id="u1")
    board.register_task(task_id="t1", capability="research", goal="done task")
    board.upsert_from_signal(report("t1", "DONE", "finished report"))
    assert board.get("t1") is not None
    assert board.get("t1").status == "done"
    snap = board.snapshot()
    assert len(snap["recent_completed"]) == 1
