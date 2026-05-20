from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from server.voice.stt.groq import GroqWhisper, _pcm_to_wav
from server.voice.types import TranscriptEvent


class _FakeTranscription:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeTranscriptions:
    def __init__(self, text: str) -> None:
        self._text = text

    async def create(self, **kwargs: object) -> _FakeTranscription:
        assert kwargs["model"] == "whisper-large-v3-turbo"
        file_arg = kwargs["file"]
        assert isinstance(file_arg, tuple)
        assert file_arg[0] == "utterance.wav"
        return _FakeTranscription(self._text)


class _FakeAudio:
    def __init__(self, text: str) -> None:
        self.transcriptions = _FakeTranscriptions(text)


class _FakeGroqClient:
    def __init__(self, text: str) -> None:
        self.audio = _FakeAudio(text)


@pytest.mark.asyncio
async def test_groq_whisper_transcribes_buffered_pcm() -> None:
    backend = GroqWhisper(api_key="test-key")
    backend._client = _FakeGroqClient("hello there")  # type: ignore[assignment]

    async def chunks() -> AsyncIterator[bytes]:
        yield b"\x00\x01" * 800

    events = [event async for event in backend.transcribe_stream(chunks())]
    assert events == [TranscriptEvent(text="hello there", is_final=True)]


def test_pcm_to_wav_roundtrip_header() -> None:
    pcm = b"\x00\x00" * 160
    wav = _pcm_to_wav(pcm, sample_rate=16000)
    assert wav[:4] == b"RIFF"
    assert len(wav) > len(pcm)
