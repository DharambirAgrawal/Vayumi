"""Lightweight speaker identity helpers for owner voice detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging

from typing import Optional

try:
    import librosa
    import numpy as np
    _SPEAKER_RECOGNITION_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SPEAKER_RECOGNITION_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class VoiceProfile:
    speaker_label: str
    embedding: list[float]
    enrolled_at: datetime = field(default_factory=datetime.utcnow)
    sample_count: int = 1


@dataclass
class SpeakerIdentityResult:
    speaker_label: str
    confidence: float
    similarity: float
    is_owner: bool
    threshold: float


class SpeakerRecognitionEngine:
    """Simple speaker identity engine built around an owner voice profile."""

    def __init__(self, match_threshold: float = 0.75):
        self.match_threshold = match_threshold
        self._profiles: dict[str, VoiceProfile] = {}

    def _require_deps(self) -> None:
        """Raise RuntimeError if optional speaker-recognition dependencies are missing."""
        if not _SPEAKER_RECOGNITION_AVAILABLE:
            raise RuntimeError(
                "Speaker recognition requires 'librosa' and 'numpy'. "
                "Install them with: pip install librosa numpy"
            )

    def enroll_owner(self, session_id: str, audio_data: bytes, sample_rate: int = 16000) -> VoiceProfile:
        self._require_deps()
        embedding = self._extract_embedding(audio_data, sample_rate)
        profile = VoiceProfile(speaker_label="owner", embedding=embedding.tolist())
        self._profiles[session_id] = profile
        logger.info("Enrolled owner voice profile for session %s", session_id)
        return profile

    def identify(self, session_id: str, audio_data: bytes, sample_rate: int = 16000) -> SpeakerIdentityResult:
        self._require_deps()
        profile = self._profiles.get(session_id)
        if profile is None:
            return SpeakerIdentityResult(
                speaker_label="unknown",
                confidence=0.0,
                similarity=0.0,
                is_owner=False,
                threshold=self.match_threshold,
            )

        embedding = self._extract_embedding(audio_data, sample_rate)
        owner_embedding = np.asarray(profile.embedding, dtype=np.float32)
        similarity = self._cosine_similarity(owner_embedding, embedding)
        confidence = float(max(0.0, min(1.0, similarity)))
        is_owner = similarity >= self.match_threshold

        return SpeakerIdentityResult(
            speaker_label=profile.speaker_label if is_owner else "guest",
            confidence=confidence,
            similarity=similarity,
            is_owner=is_owner,
            threshold=self.match_threshold,
        )

    def clear_session(self, session_id: str) -> None:
        self._profiles.pop(session_id, None)

    def has_profile(self, session_id: str) -> bool:
        return session_id in self._profiles

    def _extract_embedding(self, audio_data: bytes, sample_rate: int) -> np.ndarray:
        if not audio_data:
            return np.zeros(20, dtype=np.float32)

        samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.size == 0:
            return np.zeros(20, dtype=np.float32)

        if samples.size < sample_rate // 4:
            pad_size = (sample_rate // 4) - samples.size
            samples = np.pad(samples, (0, pad_size), mode="constant")

        mfcc = librosa.feature.mfcc(y=samples, sr=sample_rate, n_mfcc=10)
        centroid = librosa.feature.spectral_centroid(y=samples, sr=sample_rate)
        bandwidth = librosa.feature.spectral_bandwidth(y=samples, sr=sample_rate)
        rolloff = librosa.feature.spectral_rolloff(y=samples, sr=sample_rate)
        zcr = librosa.feature.zero_crossing_rate(samples)
        rms = librosa.feature.rms(y=samples)

        feature_vector = np.concatenate([
            mfcc.mean(axis=1),
            mfcc.std(axis=1),
            centroid.mean(axis=1),
            bandwidth.mean(axis=1),
            rolloff.mean(axis=1),
            zcr.mean(axis=1),
            rms.mean(axis=1),
        ]).astype(np.float32)

        norm = np.linalg.norm(feature_vector)
        if norm > 0:
            feature_vector = feature_vector / norm
        return feature_vector

    def _cosine_similarity(self, first: np.ndarray, second: np.ndarray) -> float:
        if first.size == 0 or second.size == 0:
            return 0.0

        first_norm = np.linalg.norm(first)
        second_norm = np.linalg.norm(second)
        if first_norm == 0 or second_norm == 0:
            return 0.0

        similarity = float(np.dot(first, second) / (first_norm * second_norm))
        return max(-1.0, min(1.0, similarity))