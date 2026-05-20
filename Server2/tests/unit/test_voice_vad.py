from __future__ import annotations

import numpy as np

from server.voice.vad.silero import FRAME_SAMPLES, SileroVAD


def test_silero_vad_accepts_silence_frame() -> None:
    vad = SileroVAD()
    silence = np.zeros(FRAME_SAMPLES, dtype=np.int16).tobytes()
    event = vad.accept_frame(silence)
    assert event.kind in ("silence", "speech_start", "speech_end")
