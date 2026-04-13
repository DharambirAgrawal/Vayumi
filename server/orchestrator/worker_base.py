from __future__ import annotations

import multiprocessing as mp
import queue
from typing import Any, Callable, Iterator, Optional

from .constants import WorkerEvent


class LiteRTWorker:
    def __init__(self, worker_fn: Callable[..., None], worker_args: tuple[Any, ...]):
        self._ctx = mp.get_context("spawn")
        self._req_q: mp.Queue = self._ctx.Queue()
        self._resp_q: mp.Queue = self._ctx.Queue()
        self._worker_fn = worker_fn
        self._worker_args = worker_args
        self._proc: Optional[mp.Process] = None

    def start(self) -> None:
        if self._proc and self._proc.is_alive():
            return
        self._proc = self._ctx.Process(
            target=self._worker_fn,
            args=(*self._worker_args, self._req_q, self._resp_q),
            daemon=True,
        )
        self._proc.start()

    def is_alive(self) -> bool:
        return bool(self._proc and self._proc.is_alive())

    def request(self, payload: dict, timeout: float = 30.0) -> dict:
        self._req_q.put(payload)
        try:
            return self._resp_q.get(timeout=timeout)
        except queue.Empty:
            return {"ok": False, "error": "Worker response timeout"}

    def stream(self, payload: dict, timeout_s: float = 30.0) -> Iterator[dict]:
        self._req_q.put(payload)
        while True:
            if self._proc and not self._proc.is_alive() and self._resp_q.empty():
                yield {"ok": False, "error": "Worker died"}
                break
            try:
                item = self._resp_q.get(timeout=timeout_s)
            except queue.Empty:
                yield {"ok": False, "error": "Worker stream timeout"}
                break

            if isinstance(item, dict):
                yield item
                if item.get("event") == WorkerEvent.DONE:
                    break
            else:
                yield {"ok": False, "error": "Invalid worker response"}
                break

    def stop(self, timeout: float = 1.0) -> None:
        if not self._proc:
            return
        if self._proc.is_alive():
            try:
                self._req_q.put({"cmd": "stop"})
            except Exception:
                pass
            self._proc.join(timeout=timeout)
            if self._proc.is_alive():
                self._proc.terminate()
                self._proc.join(timeout=timeout)
