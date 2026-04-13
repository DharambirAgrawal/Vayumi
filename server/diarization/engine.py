"""Speaker diarization engine."""
import logging
from typing import Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DiarizationResult:
    """Result from speaker diarization."""
    speaker: str  # e.g., "Speaker_0", "Speaker_1"
    start_ms: int
    end_ms: int
    text: str
    confidence: float


class DiarizationEngine:
    """Speaker diarization engine for meeting mode."""
    
    def __init__(self, provider: str = "pyannote"):
        """Initialize diarization engine.
        
        Args:
            provider: Diarization provider ("pyannote", "google", "azure", etc.)
        """
        self.provider = provider
        logger.info(f"Initialized Diarization engine with provider: {provider}")
    
    async def diarize(
        self,
        audio_data: bytes,
        num_speakers: Optional[int] = None,
        session_id: Optional[str] = None,
        text: str = "",
        speaker_hint: Optional[str] = None,
        start_ms: int = 0,
        end_ms: Optional[int] = None,
    ) -> List[DiarizationResult]:
        """
        Perform speaker diarization on audio.
        
        Args:
            audio_data: Audio data as bytes (16-bit PCM, 16kHz mono)
            num_speakers: Optional hint on number of speakers
            session_id: Optional session ID for logging
            
        Returns:
            List of DiarizationResult objects
        """
        duration_ms = max(0, (len(audio_data) * 1000) // (16000 * 2))
        computed_end_ms = end_ms if end_ms is not None else start_ms + duration_ms

        logger.info(
            "Starting diarization for session %s: %s bytes, %s speakers",
            session_id,
            len(audio_data),
            num_speakers,
        )

        # Low-latency fallback diarization: emit a single timestamped segment
        # using the best available speaker hint until a full provider is plugged in.
        speaker = speaker_hint.strip() if speaker_hint else "speaker_0"
        confidence = 0.9 if speaker_hint else 0.55

        result = DiarizationResult(
            speaker=speaker,
            start_ms=start_ms,
            end_ms=max(start_ms, computed_end_ms),
            text=text.strip(),
            confidence=confidence,
        )

        logger.info("Diarization complete for session %s", session_id)
        return [result]
