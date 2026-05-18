from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
from pykokoro import KokoroPipeline, PipelineConfig

from server.logger import get_logger
from server.voice.types import PcmFrame

log = get_logger("voice.tts.kokoro")

OUTPUT_SAMPLE_RATE = 16000
KOKORO_SAMPLE_RATE = 24000
FRAME_MS = 20
FRAME_SAMPLES = OUTPUT_SAMPLE_RATE * FRAME_MS // 1000
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


class KokoroTTS:
    def __init__(self, *, model_dir: Path, voice: str) -> None:
        self._voice = voice
        config: dict[str, object] = {"voice": voice}
        if model_dir.exists():
            config["model_path"] = model_dir
        self._pipeline = KokoroPipeline(PipelineConfig(**config))
        log.info("tts.kokoro.ready", voice=voice, model_dir=str(model_dir))

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[PcmFrame]:
        voice_name = voice or self._voice
        for sentence in _split_sentences(text):
            cleaned = sentence.strip()
            if not cleaned:
                continue
            pcm = await asyncio.to_thread(self._synthesize_sentence, cleaned, voice_name)
            for frame in _chunk_pcm(pcm):
                yield PcmFrame(pcm=frame, sample_rate=OUTPUT_SAMPLE_RATE)

    def _synthesize_sentence(self, text: str, voice: str) -> bytes:
        result = self._pipeline.run(text, voice=voice)
        audio = np.asarray(result.audio, dtype=np.float32)
        if audio.size == 0:
            return b""
        resampled = _resample(audio, KOKORO_SAMPLE_RATE, OUTPUT_SAMPLE_RATE)
        clipped = np.clip(resampled, -1.0, 1.0)
        int16 = (clipped * 32767.0).astype(np.int16)
        return int16.tobytes()

    async def close(self) -> None:
        await asyncio.to_thread(self._pipeline.close)


def _split_sentences(text: str) -> list[str]:
    parts = SENTENCE_RE.split(text.strip())
    if not parts:
        return [text.strip()] if text.strip() else []
    return parts


def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or audio.size == 0:
        return audio
    duration = audio.shape[0] / src_rate
    target_len = max(1, int(duration * dst_rate))
    src_times = np.linspace(0.0, duration, num=audio.shape[0], endpoint=False)
    dst_times = np.linspace(0.0, duration, num=target_len, endpoint=False)
    return np.interp(dst_times, src_times, audio)


def _chunk_pcm(pcm: bytes) -> list[bytes]:
    if not pcm:
        return []
    frame_bytes = FRAME_SAMPLES * 2
    frames: list[bytes] = []
    for offset in range(0, len(pcm), frame_bytes):
        frames.append(pcm[offset : offset + frame_bytes])
    return frames
