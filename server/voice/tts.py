# # =============================================================================
# # server/voice/tts.py — Kokoro-ONNX TTS Engine & Audio Utilities
# # =============================================================================
# #
# # PURPOSE:
# #   Wraps the Kokoro-ONNX local TTS engine for text-to-speech synthesis.
# #   Runs entirely locally (no API calls, no network). Produces high-quality
# #   natural speech from text.
# #
# # MODEL FILES REQUIRED (download separately; place under server/models/):
# #   - kokoro-v0_19.onnx (~80MB) — The ONNX model
# #   - voices.bin — Voice embeddings file
# #   Defaults: server.paths.DEFAULT_KOKORO_ONNX and DEFAULT_KOKORO_VOICES
# #
# # CLASS: TTSEngine
# #
# #   __init__(self, model_path=None, voices_path=None):
# #     - Defaults resolve to server/models/kokoro-v0_19.onnx and server/models/voices.bin
# #     - Loads Kokoro ONNX model via kokoro_onnx.Kokoro(model_path, voices_path)
# #     - default_voice = "af" (default voice ID)
# #     - _stopped = False (interrupt flag)
# #     - _paused = False (pause flag)
# #
# #   def synthesize(self, text: str) -> tuple[np.ndarray, int]:
# #     Synthesizes a single sentence. Returns (samples, sample_rate).
# #     BLOCKING CALL — must be called via asyncio.to_thread() from stream_response.
# #     Uses: self.tts.create(text, voice=self.default_voice, speed=1.0)
# #     Returns: (samples: np.ndarray float32, sample_rate: int)
# #
# #   async stop(self):
# #     Sets _stopped = True. stream_response checks this flag and breaks.
# #
# #   async pause(self):
# #     Sets _paused = True. Used by interrupt_handler for "add_context".
# #
# #   async resume(self):
# #     Sets _paused = False. Resumes after pause.
# #
# # UTILITY FUNCTION: pcm_to_wav(samples: np.ndarray, sample_rate: int) -> bytes
# #   Converts raw PCM float32 samples to WAV bytes for WebSocket transmission.
# #   Steps:
# #     1. Scale float32 [-1,1] to int16 [-32767,32767]
# #     2. Write to WAV format via wave module (1 channel, 2 bytes/sample)
# #     3. Return WAV bytes
# #   Used by stream_response in ws/handler.py.
# #
# # STREAMING PATTERN (from doc Section 10.4):
# #   LLM streams tokens → sentence boundary detector → TTS converts sentence →
# #   audio sent to client → client plays audio
# #   While first sentence plays → LLM is generating next sentence
# #   stream_response uses 1-sentence lookahead: pre-synthesizes N+1 while N streams.
# #
# # IMPORTS NEEDED:
# # =============================================================================

# import io
# import wave
# from pathlib import Path

# import numpy as np
# from kokoro_onnx import Kokoro

# from server.paths import (
#     DEFAULT_KOKORO_ONNX,
#     DEFAULT_KOKORO_VOICES,
#     MODELS_DIR,
#     SERVER_ROOT,
# )


# def _resolve_tts_path(p: str | Path | None, default: Path) -> Path:
#     if p is None:
#         return default
#     path = Path(p)
#     return path if path.is_absolute() else (SERVER_ROOT / path)


# class TTSEngine:
#     def __init__(self, model_path: str | Path | None = None,
#                  voices_path: str | Path | None = None):
#         mp = _resolve_tts_path(model_path, DEFAULT_KOKORO_ONNX)
#         vp = _resolve_tts_path(voices_path, DEFAULT_KOKORO_VOICES)
#         MODELS_DIR.mkdir(parents=True, exist_ok=True)
#         self.tts = Kokoro(str(mp), str(vp))
#         self.default_voice = "af"
#         self._stopped = False
#         self._paused = False

#     def synthesize(self, text: str) -> tuple[np.ndarray, int]:
#         pass

#     async def stop(self):
#         pass

#     async def pause(self):
#         pass

#     async def resume(self):
#         pass


# def pcm_to_wav(samples: np.ndarray, sample_rate: int) -> bytes:
#     pass


# =============================================================================
# server/voice/tts.py — Kokoro-ONNX TTS Engine & Audio Utilities
# =============================================================================

import io
import logging
import wave
from pathlib import Path

import numpy as np
from kokoro_onnx import Kokoro

from server.paths import (
    DEFAULT_KOKORO_ONNX,
    DEFAULT_KOKORO_VOICES,
    MODELS_DIR,
    SERVER_ROOT,
)

logger = logging.getLogger(__name__)


def _resolve_tts_path(p: str | Path | None, default: Path) -> Path:
    """Resolve a user-supplied path or fall back to the default model path."""
    if p is None:
        return default
    path = Path(p)
    return path if path.is_absolute() else (SERVER_ROOT / path)


class TTSEngine:
    """
    Wraps the Kokoro-ONNX local TTS engine.

    Runs entirely locally — no API calls, no network dependency.
    Produces high-quality natural speech from text.

    ``synthesize`` is a **blocking** call and MUST be invoked via
    ``asyncio.to_thread`` from the async ``stream_response`` path.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        voices_path: str | Path | None = None,
    ):
        mp = _resolve_tts_path(model_path, DEFAULT_KOKORO_ONNX)
        vp = _resolve_tts_path(voices_path, DEFAULT_KOKORO_VOICES)
        MODELS_DIR.mkdir(parents=True, exist_ok=True)

        logger.info("Loading Kokoro-ONNX model=%s voices=%s …", mp, vp)
        self.tts: Kokoro = Kokoro(str(mp), str(vp))
        logger.info("Kokoro-ONNX loaded.")

        self.default_voice: str = self._select_default_voice()
        logger.info("Using Kokoro default voice: %s", self.default_voice)
        self._stopped: bool = False
        self._paused: bool = False

    def _available_voice_names(self) -> list[str]:
        """Return available voice names from the loaded Kokoro model."""
        voices_obj = getattr(self.tts, "voices", None)
        if voices_obj is None:
            return []
        if hasattr(voices_obj, "keys"):
            try:
                return [str(k) for k in voices_obj.keys()]
            except Exception:
                pass
        if isinstance(voices_obj, dict):
            return list(voices_obj.keys())
        if isinstance(voices_obj, (list, tuple, set)):
            return [str(v) for v in voices_obj]
        return []

    def _select_default_voice(self) -> str:
        """Pick a valid default voice, preferring common voices when present."""
        available = self._available_voice_names()
        if not available:
            # Fallback for unusual runtimes; synthesis will raise if truly invalid.
            return "af"

        preferred_order = ["af", "af_heart", "alloy", "bella"]
        for preferred in preferred_order:
            if preferred in available:
                return preferred

        # Deterministic fallback: first sorted voice
        return sorted(available)[0]

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """
        Synthesize a single sentence into PCM audio.

        **BLOCKING** — call via ``asyncio.to_thread(engine.synthesize, text)``.

        Returns
        -------
        tuple[np.ndarray, int]
            ``(samples, sample_rate)`` where *samples* is a float32 array
            in the range ``[-1, 1]`` and *sample_rate* is typically 24 000.
        """
        try:
            samples, sample_rate = self.tts.create(
                text,
                voice=self.default_voice,
                speed=1.0,
            )
        except AssertionError as exc:
            # If the configured voice disappeared/mismatched, recover by switching
            # to the first available voice and retry once.
            available = self._available_voice_names()
            if not available:
                raise
            self.default_voice = sorted(available)[0]
            logger.warning(
                "Configured voice unavailable (%s). Falling back to %s",
                exc,
                self.default_voice,
            )
            samples, sample_rate = self.tts.create(
                text,
                voice=self.default_voice,
                speed=1.0,
            )
        return samples, sample_rate

    # ------------------------------------------------------------------
    # Interrupt / pause controls
    # ------------------------------------------------------------------

    async def stop(self):
        """Signal that the current streaming response should be aborted."""
        self._stopped = True

    async def pause(self):
        """Pause streaming (e.g. while the user adds context mid-response)."""
        self._paused = True

    async def resume(self):
        """Resume a previously paused stream."""
        self._paused = False


# ======================================================================
# Audio utility
# ======================================================================

def pcm_to_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    """
    Convert raw PCM float32 samples to a complete WAV byte-string.

    Parameters
    ----------
    samples:
        Float32 array in [-1, 1].
    sample_rate:
        Sample rate in Hz (e.g. 24 000).

    Returns
    -------
    bytes
        A valid WAV file (RIFF header + 16-bit PCM data) suitable for
        transmission over the WebSocket.
    """
    # Clamp and scale float32 [-1, 1] → int16 [-32767, 32767]
    clamped = np.clip(samples, -1.0, 1.0)
    int16_samples = (clamped * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)          # mono
        wf.setsampwidth(2)          # 16-bit → 2 bytes per sample
        wf.setframerate(sample_rate)
        wf.writeframes(int16_samples.tobytes())

    return buf.getvalue()