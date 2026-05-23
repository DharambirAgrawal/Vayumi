from __future__ import annotations

from server.orchestrator.directives import (
    parse_answer_to_directives,
    parse_stop_task_directives,
    strip_directives,
)


def test_parse_answer_to() -> None:
    text = '[ANSWER_TO task_id=abc-123 answer="2024 only" mode=reply]'
    found = parse_answer_to_directives(text)
    assert len(found) == 1
    assert found[0].task_id == "abc-123"
    assert found[0].answer == "2024 only"
    assert found[0].mode == "reply"


def test_parse_stop_task() -> None:
    text = "[STOP_TASK task_id=abc-123]"
    found = parse_stop_task_directives(text)
    assert len(found) == 1
    assert found[0].task_id == "abc-123"


def test_strip_answer_and_stop() -> None:
    raw = (
        'Ok.\n[ANSWER_TO task_id=x answer="yes" mode=reply]\n'
        "[STOP_TASK task_id=y]\n"
    )
    cleaned = strip_directives(raw)
    assert "ANSWER_TO" not in cleaned
    assert "STOP_TASK" not in cleaned
    assert "Ok" in cleaned
