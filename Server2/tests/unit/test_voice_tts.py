from __future__ import annotations

import numpy as np

from server.voice.tts.kokoro import _chunk_pcm, _resample, _split_sentences


def test_split_sentences() -> None:
    parts = _split_sentences("Hello there. How are you? Great!")
    assert parts == ["Hello there.", "How are you?", "Great!"]


def test_resample_downsamples_audio() -> None:
    src = np.ones(24000, dtype=np.float32)
    out = _resample(src, 24000, 16000)
    assert out.shape[0] == 16000


def test_chunk_pcm_20ms_frames() -> None:
    pcm = b"\x00\x00" * 320
    frames = _chunk_pcm(pcm)
    assert len(frames) == 1
    assert len(frames[0]) == 640
