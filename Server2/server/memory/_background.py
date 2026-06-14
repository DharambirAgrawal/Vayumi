from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)

T = TypeVar("T", bound=BaseModel)


def summarizer_slot_hint(parallel_slots: int) -> int:
    return max(0, parallel_slots - 1)


def key_lock(locks: dict[str, asyncio.Lock], key: str) -> asyncio.Lock:
    lock = locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        locks[key] = lock
    return lock


def parse_json_model(raw: str, model: type[T]) -> T | None:
    text = raw.strip()
    if not text:
        return None
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    try:
        return model.model_validate(payload)
    except ValidationError:
        return None


def track_background_task(
    tasks: set[asyncio.Task[None]],
    task: asyncio.Task[None],
    *,
    on_crash: Callable[[Exception], None],
) -> None:
    tasks.add(task)

    def _done(t: asyncio.Task[None]) -> None:
        tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            on_crash(exc)

    task.add_done_callback(_done)
