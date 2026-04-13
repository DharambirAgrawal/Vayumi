"""Audio pipeline implementation."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from typing import Optional
import struct

from models import Session, TranscriptionSegment
from speaker import SpeakerRecognitionEngine
from stt.engine import STTEngine, TranscriptionResult

logger = logging.getLogger(__name__)


@dataclass
class VADEvent:
    """Voice Activity Detection event."""
    is_speech: bool
    timestamp: float
    event_type: str = "speech"


class AudioPipeline:
    """Handles incoming audio chunks, VAD, and buffering."""
    
    def __init__(
        self,
        sample_rate: int = 16000,
        stt_engine: Optional[STTEngine] = None,
        speaker_engine: Optional[SpeakerRecognitionEngine] = None,
        silence_duration_ms: int = 320,
        vad_threshold: float = 0.035,
    ):
        self.sample_rate = sample_rate
        self.chunk_duration_ms = 20
        self.samples_per_chunk = (sample_rate * self.chunk_duration_ms) // 1000
        self.bytes_per_chunk = self.samples_per_chunk * 2  # 16-bit = 2 bytes
        
        # Per-session audio buffers
        self.audio_buffers: dict[str, deque] = {}
        self.vad_buffer: dict[str, deque] = {}
        self._chunk_remainder: dict[str, bytes] = {}
        self.lock = asyncio.Lock()
        
        # VAD state
        self.vad_enabled = True
        self.vad_threshold = max(0.01, vad_threshold)
        self.silence_duration_ms = max(120, silence_duration_ms)
        self.silence_chunks_to_end = max(1, self.silence_duration_ms // self.chunk_duration_ms)

        self.stt_engine = stt_engine or STTEngine()
        self.speaker_engine = speaker_engine
        self._speech_active: dict[str, bool] = {}
        self._silent_chunk_count: dict[str, int] = {}
    
    async def process_chunk(self, session_id: str, chunk: bytes) -> Optional[VADEvent]:
        """
        Process an incoming audio chunk.
        Returns VADEvent if VAD state changed, None otherwise.
        """
        async with self.lock:
            if session_id not in self.audio_buffers:
                self.audio_buffers[session_id] = deque()
                self.vad_buffer[session_id] = deque()

            combined = self._chunk_remainder.get(session_id, b"") + chunk
            if len(combined) < self.bytes_per_chunk:
                self._chunk_remainder[session_id] = combined
                return None

            vad_event: Optional[VADEvent] = None
            full_length = (len(combined) // self.bytes_per_chunk) * self.bytes_per_chunk
            processable = combined[:full_length]
            self._chunk_remainder[session_id] = combined[full_length:]

            for index in range(0, len(processable), self.bytes_per_chunk):
                frame = processable[index:index + self.bytes_per_chunk]
                frame_event = self._process_frame(session_id, frame)
                if frame_event is not None:
                    vad_event = frame_event

            return vad_event

    def _process_frame(self, session_id: str, chunk: bytes) -> Optional[VADEvent]:
        # Store in buffer
        self.audio_buffers[session_id].append(chunk)

        # Simple VAD: check RMS energy
        rms = self._calculate_rms(chunk)
        is_speech = rms > self.vad_threshold
        speech_was_active = self._speech_active.get(session_id, False)
        silent_chunk_count = self._silent_chunk_count.get(session_id, 0)

        # Track VAD state changes
        vad_event = None
        current_buffer = self.vad_buffer[session_id]

        # Treat initial VAD state as silence so first speech chunk triggers start.
        if is_speech and not speech_was_active:
            vad_event = VADEvent(is_speech=True, timestamp=0, event_type="speech_start")
            self._speech_active[session_id] = True
            self._silent_chunk_count[session_id] = 0
        elif speech_was_active and not is_speech:
            silent_chunk_count += 1
            self._silent_chunk_count[session_id] = silent_chunk_count
            if silent_chunk_count >= self.silence_chunks_to_end:
                vad_event = VADEvent(is_speech=False, timestamp=0, event_type="speech_end")
                self._speech_active[session_id] = False
                self._silent_chunk_count[session_id] = 0
        elif is_speech and speech_was_active:
            self._silent_chunk_count[session_id] = 0

        current_buffer.append({"is_speech": is_speech, "rms": rms})

        # Keep only last second of VAD history
        max_history = self.sample_rate // self.samples_per_chunk
        while len(current_buffer) > max_history:
            current_buffer.popleft()

        return vad_event
    
    async def get_buffered_audio(self, session_id: str) -> Optional[bytes]:
        """Get all buffered audio for a session."""
        async with self.lock:
            if session_id not in self.audio_buffers:
                return None
            
            buffer = self.audio_buffers[session_id]
            if not buffer:
                return None
            
            audio_data = b"".join(buffer)
            buffer.clear()
            return audio_data
    
    async def flush(self, session_id: str) -> Optional[TranscriptionResult]:
        """
        End audio stream for session and run STT.
        """
        audio_data = await self.get_buffered_audio(session_id)
        if not audio_data:
            return None

        return await self.transcribe_audio(session_id, audio_data)

    async def transcribe_audio(self, session_id: str, audio_data: bytes) -> Optional[TranscriptionResult]:
        """Run STT + speaker ID for raw PCM data captured for a session."""
        if not audio_data:
            return None
        
        duration_ms = (len(audio_data) * 1000) // (self.sample_rate * 2)
        logger.info(f"Flushed {len(audio_data)} bytes ({duration_ms}ms) for session {session_id}")

        transcription = await self.stt_engine.transcribe(
            audio_data,
            session_id=session_id,
            sample_rate=self.sample_rate,
        )

        if self.speaker_engine is not None:
            speaker_identity = self.speaker_engine.identify(
                session_id,
                audio_data,
                sample_rate=self.sample_rate,
            )
            transcription.speaker_label = speaker_identity.speaker_label
            transcription.is_owner = speaker_identity.is_owner

        return transcription
    
    async def reset_session(self, session_id: str) -> None:
        """Clear all buffers for a session."""
        async with self.lock:
            if session_id in self.audio_buffers:
                self.audio_buffers[session_id].clear()
            if session_id in self.vad_buffer:
                self.vad_buffer[session_id].clear()
            self._speech_active.pop(session_id, None)
            self._silent_chunk_count.pop(session_id, None)
            self._chunk_remainder.pop(session_id, None)
    
    def _calculate_rms(self, chunk: bytes) -> float:
        """Calculate RMS energy of audio chunk."""
        try:
            # Unpack 16-bit samples
            samples = struct.unpack(f"{len(chunk)//2}h", chunk)
            sum_squares = sum(s * s for s in samples)
            rms = (((sum_squares / len(samples)) ** 0.5) / 32768.0) * 4.0
            return rms
        except Exception as e:
            logger.error(f"Error calculating RMS: {e}")
            return 0.0
    
    async def get_session_transcript(self, session: Session) -> str:
        """Get full transcript for a session."""
        segments = sorted(session.transcriptions, key=lambda x: x.start_ms)
        return "\n".join(seg.text for seg in segments)
