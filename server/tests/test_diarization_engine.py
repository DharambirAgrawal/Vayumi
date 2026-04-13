"""Tests for diarization engine behavior in meeting mode."""

import pytest

from diarization.engine import DiarizationEngine


@pytest.mark.asyncio
async def test_diarization_returns_timestamped_segment_with_hint():
    engine = DiarizationEngine(provider="pyannote")
    # 1600 samples @ 16-bit mono = 3200 bytes ~= 100ms at 16kHz
    audio_data = b"\x00\x00" * 1600

    segments = await engine.diarize(
        audio_data,
        session_id="session-1",
        text="Project update",
        speaker_hint="owner",
        start_ms=500,
        end_ms=620,
    )

    assert len(segments) == 1
    segment = segments[0]
    assert segment.speaker == "owner"
    assert segment.text == "Project update"
    assert segment.start_ms == 500
    assert segment.end_ms == 620
    assert segment.confidence >= 0.8


@pytest.mark.asyncio
async def test_diarization_uses_fallback_speaker_without_hint():
    engine = DiarizationEngine(provider="pyannote")
    # 3200 samples => 200ms
    audio_data = b"\x00\x00" * 3200

    segments = await engine.diarize(audio_data, text="Hello")

    assert len(segments) == 1
    segment = segments[0]
    assert segment.speaker == "speaker_0"
    assert segment.text == "Hello"
    assert segment.end_ms >= segment.start_ms
