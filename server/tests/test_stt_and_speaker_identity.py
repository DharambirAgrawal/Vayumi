"""Tests for the Groq STT wrapper and speaker identity helper."""

import pytest
import numpy as np

from speaker import SpeakerRecognitionEngine
from stt.engine import STTEngine, TranscriptionResult
from audio.pipeline import AudioPipeline


@pytest.mark.asyncio
async def test_stt_engine_uses_transcription_result(monkeypatch):
    engine = STTEngine(api_key="test-key")

    async def fake_transcribe(audio_data, sample_rate=16000):
        return "hello from groq"

    monkeypatch.setattr(engine, "_transcribe_with_groq", fake_transcribe)

    result = await engine.transcribe(b"\x00\x00" * 320)

    assert isinstance(result, TranscriptionResult)
    assert result.text == "hello from groq"
    assert result.final is True


def test_speaker_identity_engine_owner_match(monkeypatch):
    engine = SpeakerRecognitionEngine(match_threshold=0.75)

    owner_embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    guest_embedding = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    monkeypatch.setattr(engine, "_extract_embedding", lambda audio_data, sample_rate=16000: owner_embedding)
    engine.enroll_owner("session-1", b"owner-audio")

    result_owner = engine.identify("session-1", b"owner-audio")
    assert result_owner.is_owner is True
    assert result_owner.speaker_label == "owner"

    monkeypatch.setattr(engine, "_extract_embedding", lambda audio_data, sample_rate=16000: guest_embedding)
    result_guest = engine.identify("session-1", b"guest-audio")
    assert result_guest.is_owner is False
    assert result_guest.speaker_label == "guest"


@pytest.mark.asyncio
async def test_audio_pipeline_flush_adds_speaker_metadata(monkeypatch):
    class DummySTT:
        async def transcribe(self, audio_data, session_id=None, sample_rate=16000):
            return TranscriptionResult(text="owner said hello", confidence=0.9, final=True)

    class DummySpeaker:
        def identify(self, session_id, audio_data, sample_rate=16000):
            return type(
                "Identity",
                (),
                {
                    "speaker_label": "owner",
                    "is_owner": True,
                },
            )()

    pipeline = AudioPipeline(sample_rate=16000, stt_engine=DummySTT(), speaker_engine=DummySpeaker())

    chunk = b"\x00\x00" * 320
    await pipeline.process_chunk("session-1", chunk)

    result = await pipeline.flush("session-1")

    assert result is not None
    assert result.text == "owner said hello"
    assert result.speaker_label == "owner"
    assert result.is_owner is True