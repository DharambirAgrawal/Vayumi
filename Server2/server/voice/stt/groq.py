from __future__ import annotations

import io
import wave
from collections.abc import AsyncIterator

from groq import AsyncGroq

from server.logger import get_logger
from server.voice.types import TranscriptEvent

log = get_logger("voice.stt.groq")

SAMPLE_RATE = 16000
WHISPER_MODEL = "whisper-large-v3-turbo"


class GroqWhisper:
    def __init__(self, *, api_key: str) -> None:
        self._client = AsyncGroq(api_key=api_key)

    async def transcribe_stream(
        self,
        chunks: AsyncIterator[bytes],
    ) -> AsyncIterator[TranscriptEvent]:
        pcm = await _collect_pcm(chunks)
        if not pcm:
            return

        wav_bytes = _pcm_to_wav(pcm, sample_rate=SAMPLE_RATE)
        log.debug("stt.groq.request", bytes=len(wav_bytes))

        result = await self._client.audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=("utterance.wav", wav_bytes),
            response_format="verbose_json",
            temperature=0.0,
        )

        text = (result.text or "").strip()
        if not text:
            return

        yield TranscriptEvent(text=text, is_final=True)


async def _collect_pcm(chunks: AsyncIterator[bytes]) -> bytes:
    parts: list[bytes] = []
    async for chunk in chunks:
        if chunk:
            parts.append(chunk)
    return b"".join(parts)


def _pcm_to_wav(pcm: bytes, *, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return buffer.getvalue()
