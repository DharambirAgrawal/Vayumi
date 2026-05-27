from __future__ import annotations

from server.orchestrator.directives import plan_acknowledgment, strip_directives


def test_plan_acknowledgment_before_delegate() -> None:
    raw = (
        "I'll check the latest on NVIDIA for you.\n"
        '[DELEGATE capability=main goal="nvidia stock" '
        'payload={"tool":"web_search","args":{"query":"nvidia"}}]'
    )
    assert plan_acknowledgment(raw) == "I'll check the latest on NVIDIA for you."
    assert "DELEGATE" not in strip_directives(raw)


def test_streaming_tts_strips_delegate_from_sentence() -> None:
    raw = (
        '[DELEGATE capability=main goal="x" payload={"tool":"web_search","args":{"query":"q"}}]\n'
        "Here is the answer."
    )
    assert "DELEGATE" not in strip_directives(raw)
    assert "Here is the answer" in strip_directives(raw)
