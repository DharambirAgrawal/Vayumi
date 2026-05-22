from __future__ import annotations

from server.voice.transcript import (
    is_meaningful_transcript,
    voice_pcm_is_viable,
)


def test_junk_transcripts_rejected() -> None:
    assert not is_meaningful_transcript("")
    assert not is_meaningful_transcript(".")
    assert not is_meaningful_transcript("  .  ")
    assert not is_meaningful_transcript("!")


def test_real_transcripts_accepted() -> None:
    assert is_meaningful_transcript("hey")
    assert is_meaningful_transcript("tell me a story")


def test_voice_pcm_minimum() -> None:
    assert not voice_pcm_is_viable([b"\x00" * 100])
    assert voice_pcm_is_viable([b"\x00" * 10_000])
