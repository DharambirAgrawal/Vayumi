# =============================================================================
# server/voice/vad.py — Voice Activity Detection (Echo-Aware)
# =============================================================================
#
# PURPOSE:
#   Detects whether incoming audio contains human speech. Echo-aware: uses
#   different thresholds depending on whether Vayumi is currently speaking
#   (playback_state). This prevents Vayumi from hearing and responding to
#   its own voice.
#
# MODEL: Silero VAD (recommended over webrtcvad)
#   - High accuracy speech detection
#   - Returns probability score per audio chunk
#   - Lightweight, fast inference
#
# TWO-LAYER ECHO CANCELLATION STRATEGY:
#   Layer 1 — Client-side:
#     ESP32: Hardware AEC via ESP-ADF (primary, subtracts speaker from mic)
#     Browser: Web Audio API echoCancellation:true
#
#   Layer 2 — Server-side state gating (THIS FILE):
#     When playback_state == "IDLE":
#       → Normal threshold (0.5 probability)
#       → Any detected speech treated as user input
#     When playback_state == "PLAYING":
#       → Raised threshold (0.8 probability)
#       → Minimum sustained duration (300ms continuous speech)
#       → Short bursts IGNORED (likely echo residue)
#       → Only loud, sustained human speech triggers interrupt
#
# CLASS: VADResult
#   has_speech: bool — whether speech was detected this chunk
#
# CLASS: VADEngine
#
#   __init__(self):
#     - self.detector = ... (silero-vad model instance)
#     - self.normal_threshold = 0.5 (probability threshold when IDLE)
#     - self.echo_threshold = 0.8 (raised threshold when PLAYING)
#     - self.min_sustained_ms = 300 (minimum speech duration to pass echo gate)
#     - self._speech_buffer_ms = 0 (accumulated speech duration tracker)
#
#   async process(self, audio_chunk: bytes, session) -> VADResult:
#     Core VAD logic. Steps:
#       1. Run detector on audio_chunk → get probability score
#       2. Check against normal_threshold → has_speech
#       3. If no speech → reset _speech_buffer_ms → return False
#       4. If session.playback_state == "PLAYING":
#            a. If probability < echo_threshold → reset buffer → return False
#            b. Calculate chunk duration in ms:
#               chunk_ms = len(audio_chunk) / (16000 * 2) * 1000  (16kHz 16-bit mono)
#            c. Accumulate: _speech_buffer_ms += chunk_ms
#            d. If _speech_buffer_ms < min_sustained_ms → return False
#       5. Reset _speech_buffer_ms → return True
#
# AUDIO FORMAT ASSUMPTIONS:
#   - 16kHz sample rate
#   - 16-bit (2 bytes per sample)
#   - Mono channel
#   These match what ESP32 sends and what Groq Whisper expects.
#
# IMPORTS NEEDED:
# =============================================================================

import logging
import numpy as np
import torch

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # 16-bit mono


class VADResult:
    """Outcome of a single VAD evaluation on one audio chunk."""

    def __init__(self, has_speech: bool):
        self.has_speech = has_speech

    def __repr__(self) -> str:
        return f"VADResult(has_speech={self.has_speech})"


class VADEngine:
    """
    Silero-based Voice Activity Detector with echo-aware gating.

    Normal mode  (playback IDLE):    probability >= 0.5 → speech
    Echo mode    (playback PLAYING): probability >= 0.8 AND sustained
                                     for >= 300 ms continuous → speech
    """

    def __init__(self):
        self.detector = None          # silero-vad model, loaded lazily
        self._silero_utils = None     # helper fns bundled with model

        self.normal_threshold: float = 0.5
        self.echo_threshold: float = 0.8
        self.min_sustained_ms: int = 300
        self._speech_buffer_ms: float = 0.0

        self._load_model()

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """Load Silero VAD from torch hub (cached after first download)."""
        try:
            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                trust_repo=True,
            )
            self.detector = model
            self._silero_utils = utils
            logger.info("Silero VAD model loaded successfully")
        except Exception:
            logger.exception("Failed to load Silero VAD model")
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _audio_bytes_to_tensor(self, audio_chunk: bytes) -> torch.Tensor:
        """
        Convert raw 16-bit PCM bytes → float32 torch tensor in [-1, 1].

        Silero VAD expects float32 samples normalised to the [-1, 1] range.
        """
        samples = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32)
        # Normalise int16 range → [-1.0, 1.0]
        samples /= 32768.0
        return torch.from_numpy(samples)

    def _get_probability(self, audio_chunk: bytes) -> float:
        """
        Run the Silero model on a single chunk and return speech probability.

        Silero VAD accepts chunk sizes of 512, 1024 or 1536 samples at 16 kHz.
        If the incoming chunk doesn't match, we pad/truncate to the nearest
        valid size so the model never receives an unexpected length.
        """
        tensor = self._audio_bytes_to_tensor(audio_chunk)
        num_samples = tensor.shape[0]

        # Silero valid window sizes at 16 kHz
        valid_sizes = [512, 1024, 1536]

        if num_samples == 0:
            return 0.0

        # If the chunk is larger than the biggest window, process the last
        # valid_size samples (most recent audio is most relevant).
        if num_samples > valid_sizes[-1]:
            tensor = tensor[-valid_sizes[-1]:]
        elif num_samples not in valid_sizes:
            # Pick the smallest valid size that fits, pad with zeros
            target = valid_sizes[-1]  # default to largest
            for vs in valid_sizes:
                if vs >= num_samples:
                    target = vs
                    break
            padded = torch.zeros(target)
            padded[:num_samples] = tensor
            tensor = padded

        with torch.no_grad():
            probability = self.detector(tensor, SAMPLE_RATE).item()

        return probability

    @staticmethod
    def _chunk_duration_ms(audio_chunk: bytes) -> float:
        """Duration of an audio chunk in milliseconds (16 kHz, 16-bit mono)."""
        num_samples = len(audio_chunk) / BYTES_PER_SAMPLE
        return (num_samples / SAMPLE_RATE) * 1000.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def process(self, audio_chunk: bytes, session) -> VADResult:
        """
        Evaluate one audio chunk for speech, respecting echo-gating.

        Parameters
        ----------
        audio_chunk : bytes
            Raw 16-bit 16 kHz mono PCM audio.
        session :
            Session object exposing ``playback_state`` (``"IDLE"`` or
            ``"PLAYING"``).

        Returns
        -------
        VADResult
            ``.has_speech`` is True only when the chunk is considered
            genuine user speech (not echo residue).
        """
        if self.detector is None:
            logger.warning("VAD model not loaded — treating chunk as no speech")
            return VADResult(has_speech=False)

        if not audio_chunk:
            self._speech_buffer_ms = 0.0
            return VADResult(has_speech=False)

        # --- Step 1: Run Silero to get probability -------------------------
        probability = self._get_probability(audio_chunk)

        # --- Step 2 / 3: Normal threshold check ----------------------------
        if probability < self.normal_threshold:
            # No speech at all → reset sustained-speech accumulator
            self._speech_buffer_ms = 0.0
            return VADResult(has_speech=False)

        # We have speech above the base threshold.

        # --- Step 4: Echo-gating when Vayumi is playing back audio ---------
        playback_state = getattr(session, "playback_state", "IDLE")

        if playback_state == "PLAYING":
            # 4a. Must exceed the stricter echo threshold
            if probability < self.echo_threshold:
                self._speech_buffer_ms = 0.0
                return VADResult(has_speech=False)

            # 4b-c. Accumulate sustained duration
            chunk_ms = self._chunk_duration_ms(audio_chunk)
            self._speech_buffer_ms += chunk_ms

            # 4d. Not sustained long enough yet — likely echo residue
            if self._speech_buffer_ms < self.min_sustained_ms:
                return VADResult(has_speech=False)

        # --- Step 5: Genuine speech confirmed ------------------------------
        # Reset accumulator so next speech segment starts fresh
        self._speech_buffer_ms = 0.0
        return VADResult(has_speech=True)

    def reset(self) -> None:
        """Reset internal state (call on session tear-down / new turn)."""
        self._speech_buffer_ms = 0.0
        # Silero keeps internal LSTM state; reset it for a clean slate
        if self.detector is not None:
            self.detector.reset_states()