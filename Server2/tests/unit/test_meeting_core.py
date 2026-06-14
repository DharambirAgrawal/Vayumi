from __future__ import annotations

from server.orchestrator.meeting import (
    is_addressed_transcript,
    parse_mode_command,
)


def test_is_addressed_transcript_hey_vayumi() -> None:
    addressed, body = is_addressed_transcript("Hey Vayumi, what time is it?")
    assert addressed is True
    assert body == "what time is it?"


def test_is_addressed_transcript_vayumi_comma() -> None:
    addressed, body = is_addressed_transcript("Vayumi, summarize the meeting")
    assert addressed is True
    assert body == "summarize the meeting"


def test_is_addressed_transcript_passive() -> None:
    addressed, body = is_addressed_transcript("We should ship next week")
    assert addressed is False
    assert body == "We should ship next week"


def test_parse_mode_command_end() -> None:
    assert parse_mode_command("please end meeting mode now") == "end"


def test_parse_mode_command_start() -> None:
    assert parse_mode_command("start meeting mode") == "start"


def test_parse_mode_command_none() -> None:
    assert parse_mode_command("what is on the agenda") is None
