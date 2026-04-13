"""Local wake-word detection layer.

This module is intentionally optional: if local detection dependencies are not
installed, the server falls back to transcript-based wake detection.
"""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import contextlib
import io
import importlib
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class WakeWordDetectionResult:
    detected: bool
    confidence: float = 0.0
    source: str = "none"
    transcript: str = ""


class WakeWordDetector:
    """Local wake-word detector wrapper.

    Supported providers:
    - "off": disabled detector
    - "openwakeword": local OpenWakeWord model scoring
    - "local_whisper": local Whisper transcription on short buffers
    """

    def __init__(
        self,
        provider: str = "off",
        threshold: float = 0.45,
        model_path: Optional[str] = None,
        wake_word_name: str = "vayumi",
        whisper_model_name: str = "tiny.en",
        whisper_language: str = "en",
    ) -> None:
        self.provider = provider.lower().strip()
        self.threshold = max(0.0, min(1.0, threshold))
        self.model_path = (model_path or "").strip() or None
        self.wake_word_name = wake_word_name.lower().strip() or "vayumi"

        self._model = None
        self._model_labels: list[str] = []
        self._whisper_model = None
        self._whisper_model_name = whisper_model_name.strip() or "tiny.en"
        self._whisper_language = whisper_language.strip() or "en"

        if self.provider == "off":
            logger.info("Wake-word detector disabled")
            return

        if self.provider == "openwakeword":
            self._init_openwakeword()
        elif self.provider == "local_whisper":
            logger.info(
                "Wake-word detector initialized with local Whisper (model=%s, language=%s)",
                self._whisper_model_name,
                self._whisper_language,
            )
        else:
            logger.warning("Unknown wake-word provider '%s'; detector disabled", self.provider)
            self.provider = "off"

    @property
    def enabled(self) -> bool:
        if self.provider == "local_whisper":
            return True
        return self.provider != "off" and self._model is not None

    async def detect(self, audio_data: bytes, sample_rate: int = 16000) -> WakeWordDetectionResult:
        """Detect wake word from PCM16 mono bytes."""
        if not self.enabled or not audio_data:
            return WakeWordDetectionResult(detected=False)

        if self.provider == "openwakeword":
            return await asyncio.to_thread(self._detect_openwakeword, audio_data, sample_rate)

        if self.provider == "local_whisper":
            return await asyncio.to_thread(self._detect_local_whisper, audio_data, sample_rate)

        return WakeWordDetectionResult(detected=False)

    def _detect_local_whisper(self, audio_data: bytes, sample_rate: int) -> WakeWordDetectionResult:
        try:
            whisper_module = importlib.import_module("whisper")
        except Exception as exc:
            logger.warning("local whisper is not available (%s). Falling back to disabled wake detector.", exc)
            self.provider = "off"
            return WakeWordDetectionResult(detected=False)

        if self._whisper_model is None:
            try:
                self._whisper_model = whisper_module.load_model(self._whisper_model_name)
            except Exception as exc:
                logger.warning("Failed to load local whisper model (%s). Falling back to disabled wake detector.", exc)
                self.provider = "off"
                return WakeWordDetectionResult(detected=False)

        pcm = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        if pcm.size == 0:
            return WakeWordDetectionResult(detected=False)

        if sample_rate != 16000:
            logger.debug("Local Whisper wake detector expects 16kHz audio; got %s", sample_rate)

        try:
            # Whisper prints progress bars to stdout/stderr; silence them for wake checks.
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = self._whisper_model.transcribe(
                    pcm,
                    language=self._whisper_language,
                    fp16=False,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    initial_prompt="Wake word is Vayumi. Possible spellings: Vayumi, Wayumi, Vai Umi, Vaiyumi.",
                    verbose=False,
                )
        except Exception as exc:
            logger.warning("Local whisper wake detection failed: %s", exc)
            return WakeWordDetectionResult(detected=False)

        transcript = str(result.get("text", "")).strip().lower()
        if not transcript:
            return WakeWordDetectionResult(detected=False)

        normalized = transcript.replace("-", " ").replace("_", " ")
        matched = self.wake_word_name in normalized or any(
            token in normalized for token in {"vayumi", "wayumi", "vai umi", "vaiyumi"}
        )
        return WakeWordDetectionResult(
            detected=matched,
            confidence=0.82 if matched else 0.0,
            source="local_whisper",
            transcript=transcript,
        )

    def _init_openwakeword(self) -> None:
        try:
            model_module = importlib.import_module("openwakeword.model")
            Model = getattr(model_module, "Model")
        except Exception as exc:
            logger.warning(
                "openwakeword is not available (%s). Falling back to transcript wake detection.",
                exc,
            )
            self.provider = "off"
            return

        try:
            if self.model_path:
                self._model = Model(wakeword_models=[self.model_path])
            else:
                # If no custom model is provided, OpenWakeWord will load its defaults.
                self._model = Model()

            if hasattr(self._model, "models") and isinstance(self._model.models, dict):
                self._model_labels = [str(label).lower() for label in self._model.models.keys()]

            logger.info(
                "Wake-word detector initialized with OpenWakeWord (models=%s threshold=%.2f)",
                ",".join(self._model_labels) if self._model_labels else "default",
                self.threshold,
            )
        except Exception as exc:
            logger.warning(
                "Failed to initialize OpenWakeWord (%s). Falling back to transcript wake detection.",
                exc,
            )
            self.provider = "off"
            self._model = None
            self._model_labels = []

    def _detect_openwakeword(self, audio_data: bytes, sample_rate: int) -> WakeWordDetectionResult:
        if self._model is None:
            return WakeWordDetectionResult(detected=False)

        if sample_rate != 16000:
            logger.debug("OpenWakeWord expects 16kHz audio; got %s", sample_rate)

        # OpenWakeWord expects float32 audio chunks. The model operates on
        # a rolling buffer, so we feed it in small fixed windows.
        pcm = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        if pcm.size == 0:
            return WakeWordDetectionResult(detected=False)

        chunk_size = 1280  # 80 ms at 16kHz
        max_score = 0.0
        matched_label = ""

        for start in range(0, pcm.size, chunk_size):
            chunk = pcm[start:start + chunk_size]
            if chunk.size < chunk_size:
                padded = np.zeros((chunk_size,), dtype=np.float32)
                padded[:chunk.size] = chunk
                chunk = padded

            predictions = self._model.predict(chunk)
            if not isinstance(predictions, dict):
                continue

            for label, score in predictions.items():
                label_lower = str(label).lower()
                score_value = float(score)
                if score_value > max_score:
                    max_score = score_value
                    matched_label = label_lower

        matched = self.wake_word_name in matched_label if matched_label else False
        detected = matched and max_score >= self.threshold

        return WakeWordDetectionResult(
            detected=detected,
            confidence=max_score,
            source="openwakeword",
        )
