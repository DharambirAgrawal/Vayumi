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

import numpy as np


class VADResult:
    def __init__(self, has_speech: bool):
        self.has_speech = has_speech


class VADEngine:
    def __init__(self):
        self.detector = None  # silero-vad model, loaded at startup
        self.normal_threshold: float = 0.5
        self.echo_threshold: float = 0.8
        self.min_sustained_ms: int = 300
        self._speech_buffer_ms: float = 0

    async def process(self, audio_chunk: bytes, session) -> VADResult:
        pass
