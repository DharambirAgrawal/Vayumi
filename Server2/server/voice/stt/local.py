from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import numpy as np
from faster_whisper import WhisperModel

from server.logger import get_logger
from server.voice.types import TranscriptEvent

log = get_logger("voice.stt.local")

SAMPLE_RATE = 16000


class LocalFasterWhisper:
    def __init__(self, *, model: str, device: str = "cpu", compute_type: str = "int8") -> None:
        self._model_name = model
        self._model = WhisperModel(model, device=device, compute_type=compute_type)
        log.info(
            "stt.local.ready",
            model=model,
            device=device,
            compute_type=compute_type,
        )

    async def transcribe_stream(
        self,
        chunks: AsyncIterator[bytes],
    ) -> AsyncIterator[TranscriptEvent]:
        pcm = await _collect_pcm(chunks)
        if not pcm:
            return

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        text = await asyncio.to_thread(self._transcribe, audio)
        text = text.strip()
        if not text:
            return
        yield TranscriptEvent(text=text, is_final=True)

    def _transcribe(self, audio: np.ndarray) -> str:
        segments, _info = self._model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=True,
        )
        parts: list[str] = []
        for segment in segments:
            chunk = segment.text.strip()
            if chunk:
                parts.append(chunk)
        return " ".join(parts)


async def _collect_pcm(chunks: AsyncIterator[bytes]) -> bytes:
    parts: list[bytes] = []
    async for chunk in chunks:
        if chunk:
            parts.append(chunk)
    return b"".join(parts)
