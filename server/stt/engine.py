"""Speech-to-Text engine."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import io
import logging
import os
import wave
from typing import Optional, AsyncIterator

import httpx

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    """Result from STT."""

    text: str
    confidence: float
    final: bool
    partial_text: Optional[str] = None
    speaker_label: Optional[str] = None
    is_owner: Optional[bool] = None


class STTEngine:
    """Speech-to-Text engine for converting audio to text."""

    def __init__(
        self,
        provider: str = "whisper",
        model: str = "whisper-large-v3",
        api_key: Optional[str] = None,
        base_url: str = "https://api.groq.com/openai/v1",
        prompt: str = "",
        language: str = "en",
        request_timeout_seconds: float = 30.0,
    ):
        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "").strip()
        self.base_url = base_url.rstrip("/")
        self.prompt = prompt.strip()
        self.language = (language or "en").strip() or "en"
        self.request_timeout_seconds = max(5.0, request_timeout_seconds)
        self._http_client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.request_timeout_seconds,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
        )
        logger.info(
            "Initialized STT engine with provider=%s model=%s groq=%s",
            self.provider,
            self.model,
            bool(self.api_key),
        )

    @classmethod
    def from_env(
        cls,
        provider: str,
        model: str,
        base_url: str,
        prompt: str = "",
        language: str = "en",
        request_timeout_seconds: float = 30.0,
    ) -> "STTEngine":
        return cls(
            provider=provider,
            model=model,
            base_url=base_url,
            prompt=prompt,
            language=language,
            request_timeout_seconds=request_timeout_seconds,
        )

    async def transcribe_stream(
        self,
        audio_data: bytes,
        session_id: Optional[str] = None,
        sample_rate: int = 16000,
    ) -> AsyncIterator[TranscriptionResult]:
        """Transcribe audio and yield the final result."""

        logger.info(
            "Starting STT transcription for session %s: %s bytes",
            session_id,
            len(audio_data),
        )

        text = await self._transcribe_with_groq(audio_data, sample_rate=sample_rate)
        confidence = 0.0 if not text else 0.92
        yield TranscriptionResult(text=text, confidence=confidence, final=True)

        logger.info("STT transcription complete for session %s", session_id)

    async def transcribe(
        self,
        audio_data: bytes,
        session_id: Optional[str] = None,
        sample_rate: int = 16000,
    ) -> TranscriptionResult:
        """Return a single transcription result."""

        async for result in self.transcribe_stream(audio_data, session_id=session_id, sample_rate=sample_rate):
            return result

        return TranscriptionResult(text="", confidence=0.0, final=True)

    async def cancel(self, session_id: str) -> None:
        """Cancel ongoing transcription for a session."""

        logger.info("Cancelled STT transcription for session %s", session_id)

    async def close(self) -> None:
        """Close underlying HTTP resources."""
        await self._http_client.aclose()

    async def _transcribe_with_groq(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not configured")

        wav_data = self._pcm16_to_wav(audio_data, sample_rate=sample_rate)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        files = {
            "file": ("audio.wav", wav_data.getvalue(), "audio/wav"),
        }
        data = {
            "model": self.model,
            "response_format": "json",
            "temperature": "0",
            "language": self.language,
        }
        if self.prompt:
            data["prompt"] = self.prompt
        response = await self._http_client.post("/audio/transcriptions", headers=headers, files=files, data=data)
        response.raise_for_status()
        payload = response.json()

        text = str(payload.get("text", "")).strip()
        if not text:
            logger.warning("Groq transcription returned an empty result")
        return text

    def _pcm16_to_wav(self, audio_data: bytes, sample_rate: int = 16000) -> io.BytesIO:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_data)
        buffer.seek(0)
        return buffer
