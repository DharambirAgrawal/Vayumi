"""Text-to-Speech engine."""
from __future__ import annotations

import asyncio
import logging
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, AsyncIterator

import numpy as np
from scipy.signal import resample_poly

try:
    from kokoro_onnx import Kokoro, SAMPLE_RATE as KOKORO_SAMPLE_RATE
except Exception:  # pragma: no cover - optional dependency
    Kokoro = None  # type: ignore[assignment]
    KOKORO_SAMPLE_RATE = 24000

logger = logging.getLogger(__name__)


@dataclass
class TTSRequest:
    """TTS request parameters."""
    text: str
    voice: str = "default"
    speed: float = 1.0
    language: str = "en-US"


class TTSEngine:
    """Text-to-Speech engine for converting text to audio."""
    
    def __init__(
        self,
        provider: str = "kokoro_onnx",
        sample_rate: int = 16000,
        voice: str = "af_heart",
        fallback_voice: str = "Samantha",
        allow_system_fallback: bool = False,
        model_path: Optional[str] = None,
        voices_path: Optional[str] = None,
        speed: float = 1.0,
    ):
        """Initialize TTS engine.
        
        Args:
            provider: TTS provider ("piper", "elevenlabs", "google", etc.)
            sample_rate: Output sample rate in Hz
        """
        self.provider = provider.lower().strip()
        self.sample_rate = sample_rate
        self.voice = voice
        self.fallback_voice = fallback_voice
        self.allow_system_fallback = allow_system_fallback
        self.model_path = model_path
        self.voices_path = voices_path
        self.speed = speed
        self.cancelled_sessions: set[str] = set()
        self._kokoro: Optional[Kokoro] = None
        self._kokoro_ready = False
        self._maybe_init_kokoro()
        logger.info(f"Initialized TTS engine with provider: {self.provider}")

    def _maybe_init_kokoro(self) -> None:
        if self.provider not in {"kokoro", "kokoro_onnx", "kokoro-onnx"}:
            return

        if Kokoro is None:
            if self.allow_system_fallback:
                logger.warning("kokoro_onnx is not installed; falling back to macOS say")
                self.provider = "macos_say"
            else:
                logger.warning("kokoro_onnx is not installed; TTS disabled (no system fallback)")
                self.provider = "none"
            return

        model_path = Path(self.model_path or "") if self.model_path else None
        voices_path = Path(self.voices_path or "") if self.voices_path else None
        if model_path is None or voices_path is None:
            if self.allow_system_fallback:
                logger.warning("Kokoro model or voices path not configured; falling back to macOS say")
                self.provider = "macos_say"
            else:
                logger.warning("Kokoro paths missing; TTS disabled (no system fallback)")
                self.provider = "none"
            return

        if not model_path.exists() or not voices_path.exists():
            if self.allow_system_fallback:
                logger.warning(
                    "Kokoro assets missing (model=%s voices=%s); falling back to macOS say",
                    model_path,
                    voices_path,
                )
                self.provider = "macos_say"
            else:
                logger.warning(
                    "Kokoro assets missing (model=%s voices=%s); TTS disabled (no system fallback)",
                    model_path,
                    voices_path,
                )
                self.provider = "none"
            return

        self._kokoro = Kokoro(str(model_path), str(voices_path))
        self._kokoro_ready = True
    
    async def synthesize_stream(self, text: str, session_id: Optional[str] = None) -> AsyncIterator[bytes]:
        """
        Synthesize text to speech and stream audio chunks.
        
        Args:
            text: Text to convert to speech
            session_id: Optional session ID for logging
            
        Yields:
            Audio chunks as bytes (16-bit PCM, 16kHz mono)
        """
        logger.info(f"Starting TTS synthesis for session {session_id}: {text[:50]}...")

        if session_id:
            self.cancelled_sessions.discard(session_id)

        if self.provider in {"kokoro", "kokoro_onnx", "kokoro-onnx"} and self._kokoro_ready:
            async for chunk in self._synthesize_stream_kokoro(text, session_id=session_id):
                yield chunk
        elif self.provider in {"none", "disabled"}:
            logger.info("TTS disabled for session %s; not synthesizing audio", session_id)
            return
        else:
            pcm_audio = await self._synthesize_pcm_macos(text)
            chunk_size = 640  # 20 ms @ 16kHz, 16-bit mono
            for i in range(0, len(pcm_audio), chunk_size):
                if session_id and session_id in self.cancelled_sessions:
                    logger.info(f"TTS stream cancelled for session {session_id}")
                    break
                yield pcm_audio[i:i + chunk_size]
                await asyncio.sleep(0)

        logger.info(f"TTS synthesis complete for session {session_id}")

    async def _synthesize_stream_kokoro(self, text: str, session_id: Optional[str] = None) -> AsyncIterator[bytes]:
        if self._kokoro is None:
            raise RuntimeError("Kokoro engine is not initialized")

        async for audio_chunk, chunk_sample_rate in self._kokoro.create_stream(
            text,
            voice=self.voice,
            speed=self.speed,
            lang="en-us",
            trim=True,
        ):
            if session_id and session_id in self.cancelled_sessions:
                logger.info(f"TTS stream cancelled for session {session_id}")
                break
            yield self._float_audio_to_pcm16(audio_chunk, chunk_sample_rate)

    def _float_audio_to_pcm16(self, audio_chunk: np.ndarray, chunk_sample_rate: int) -> bytes:
        chunk = np.asarray(audio_chunk, dtype=np.float32).reshape(-1)
        if chunk.size == 0:
            return b""

        if chunk_sample_rate != self.sample_rate:
            chunk = resample_poly(chunk, self.sample_rate, chunk_sample_rate).astype(np.float32)

        chunk = np.clip(chunk, -1.0, 1.0)
        pcm = (chunk * 32767.0).astype(np.int16)
        return pcm.tobytes()

    async def _synthesize_pcm_macos(self, text: str) -> bytes:
        if self.provider not in {"macos_say", "say", "system"}:
            raise RuntimeError(f"Unsupported TTS provider: {self.provider}")

        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=True) as tmp_aiff, tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp_wav:
            say_process = await asyncio.create_subprocess_exec(
                "say",
                "-v",
                self.fallback_voice,
                "-o",
                tmp_aiff.name,
                text,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, say_stderr = await say_process.communicate()
            if say_process.returncode != 0:
                raise RuntimeError(f"say synthesis failed: {say_stderr.decode('utf-8', errors='ignore')}")

            convert_process = await asyncio.create_subprocess_exec(
                "afconvert",
                "-f",
                "WAVE",
                "-d",
                f"LEI16@{self.sample_rate}",
                "-c",
                "1",
                tmp_aiff.name,
                tmp_wav.name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _cstdout, convert_stderr = await convert_process.communicate()
            if convert_process.returncode != 0:
                raise RuntimeError(f"afconvert failed: {convert_stderr.decode('utf-8', errors='ignore')}")

            with wave.open(tmp_wav.name, "rb") as wf:
                if wf.getsampwidth() != 2 or wf.getnchannels() != 1 or wf.getframerate() != self.sample_rate:
                    raise RuntimeError("Converted WAV is not 16-bit mono at expected sample rate")
                frames = wf.readframes(wf.getnframes())

        return frames
    
    async def synthesize(self, text: str) -> bytes:
        """
        Synchronous synthesize - returns full audio.
        
        Args:
            text: Text to convert
            
        Returns:
            Full audio data as bytes
        """
        chunks = []
        async for chunk in self.synthesize_stream(text):
            chunks.append(chunk)
        return b"".join(chunks)
    
    async def cancel(self, session_id: str) -> None:
        """Cancel TTS synthesis for a session."""
        logger.info(f"Cancelled TTS synthesis for session {session_id}")
        self.cancelled_sessions.add(session_id)
    
    async def get_available_voices(self) -> list[dict]:
        """Get list of available voices for this provider."""
        if self.provider in {"kokoro", "kokoro_onnx", "kokoro-onnx"} and self._kokoro is not None:
            voices = []
            for voice_name in self._kokoro.get_voices():
                voices.append(
                    {
                        "id": voice_name,
                        "name": voice_name,
                        "language": "en-US",
                        "gender": "unknown",
                    }
                )
            return voices

        if self.provider not in {"macos_say", "say", "system"}:
            return [
                {
                    "id": "default",
                    "name": "Default Voice",
                    "language": "en-US",
                    "gender": "neutral",
                }
            ]

        process = await asyncio.create_subprocess_exec(
            "say",
            "-v",
            "?",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await process.communicate()
        if process.returncode != 0:
            return []

        voices = []
        for line in stdout.decode("utf-8", errors="ignore").splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            voice_id = parts[0]
            voices.append(
                {
                    "id": voice_id,
                    "name": voice_id,
                    "language": "unknown",
                    "gender": "unknown",
                }
            )
        return voices
