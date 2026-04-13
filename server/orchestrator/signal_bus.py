from __future__ import annotations

import multiprocessing as mp
import queue
from typing import Any


class SignalBus:
    def __init__(self):
        self._queues: dict[str, mp.Queue] = {}

    def get_queue(self, speaker_id: str) -> mp.Queue:
        if speaker_id not in self._queues:
            self._queues[speaker_id] = mp.Queue()
        return self._queues[speaker_id]

    def drain(self, speaker_id: str) -> list[dict[str, Any]]:
        q = self.get_queue(speaker_id)
        out: list[dict[str, Any]] = []
        while True:
            try:
                item = q.get_nowait()
                if isinstance(item, dict):
                    out.append(item)
            except queue.Empty:
                break
            except Exception:
                break
        return out


signal_bus = SignalBus()
