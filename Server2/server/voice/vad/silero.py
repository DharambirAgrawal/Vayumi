from __future__ import annotations

import numpy as np
import torch

from server.voice.types import VadEvent

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512


class SileroVAD:
    """Server-side end-of-utterance helper and test surface."""

    def __init__(self) -> None:
        from silero_vad import VADIterator, load_silero_vad

        self._model = load_silero_vad()
        self._iterator = VADIterator(self._model, sampling_rate=SAMPLE_RATE)

    def accept_frame(self, frame: bytes) -> VadEvent:
        if len(frame) < 2:
            return VadEvent(kind="silence", probability=0.0)

        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        last_prob = 0.0
        offset = 0
        while offset + FRAME_SAMPLES <= len(samples):
            window = torch.from_numpy(samples[offset : offset + FRAME_SAMPLES])
            event = self._iterator(window, return_seconds=False)
            offset += FRAME_SAMPLES
            if event:
                if "start" in event:
                    return VadEvent(kind="speech_start", probability=1.0)
                if "end" in event:
                    return VadEvent(kind="speech_end", probability=1.0)

        if offset < len(samples):
            tail = torch.from_numpy(samples[offset:])
            prob = float(self._model(tail, SAMPLE_RATE).item())
            last_prob = prob
            if prob >= self._iterator.threshold:
                return VadEvent(kind="speech_start", probability=prob)

        return VadEvent(kind="silence", probability=last_prob)

    def reset(self) -> None:
        self._iterator.reset_states()
