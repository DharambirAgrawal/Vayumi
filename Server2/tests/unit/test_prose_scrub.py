from __future__ import annotations

from server.orchestrator.prose import scrub_follow_up_prose


def test_scrub_removes_ack_and_junk() -> None:
    raw = (
        "Pulling up Tesla for you.\n"
        "!\n"
        "]\n"
        "Tesla is around $400.\n"
    )
    out = scrub_follow_up_prose(raw, spoken_ack="Pulling up Tesla for you.")
    assert "Pulling up Tesla" not in out
    assert "!" not in out
    assert "]" not in out
    assert "400" in out
