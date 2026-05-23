from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Protocol

import httpx

from server.logger import get_logger

log = get_logger("engine.pool")


class CompletionPriority(IntEnum):
    P0_MAIN = 0
    P1_SUBAGENT = 1
    P2_SUMMARIZER = 2


@dataclass(frozen=True)
class CompletionRequest:
    prompt: str
    max_tokens: int = 512
    temperature: float = 0.7
    stop: tuple[str, ...] = ()
    cache_prompt: bool = False


class CompletionClient(Protocol):
    def stream_completion(
        self,
        *,
        base_url: str,
        slot_id: int,
        request: CompletionRequest,
    ) -> AsyncIterator[str]:
        ...


class LlamaCompletionClient:
    def stream_completion(
        self,
        *,
        base_url: str,
        slot_id: int,
        request: CompletionRequest,
    ) -> AsyncIterator[str]:
        return self._stream_completion(base_url=base_url, slot_id=slot_id, request=request)

    async def _stream_completion(
        self,
        *,
        base_url: str,
        slot_id: int,
        request: CompletionRequest,
    ) -> AsyncIterator[str]:
        payload: dict[str, object] = {
            "prompt": request.prompt,
            "stream": True,
            "n_predict": request.max_tokens,
            "temperature": request.temperature,
            "cache_prompt": request.cache_prompt,
        }
        if request.stop:
            payload["stop"] = list(request.stop)

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{base_url}/completion",
                params={"slot_id": slot_id},
                json=payload,
                headers={"Accept": "text/event-stream"},
            ) as response:
                response.raise_for_status()
                buffer = ""
                async for chunk_text in response.aiter_text():
                    if not chunk_text:
                        continue
                    buffer += chunk_text
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        token = parse_completion_stream_line(line)
                        if token is not None:
                            yield token
                tail = buffer.strip()
                if tail:
                    token = parse_completion_stream_line(tail)
                    if token is not None:
                        yield token


class CompletionHandle:
    def __init__(self, request: CompletionRequest) -> None:
        self.id = str(uuid.uuid4())
        self.request = request
        self.slot_id: int | None = None
        self.cancelled = False
        self._queue: asyncio.Queue[str | BaseException | None] = asyncio.Queue()

    def __aiter__(self) -> CompletionHandle:
        return self

    async def __anext__(self) -> str:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        if isinstance(item, BaseException):
            raise item
        return item

    async def put_token(self, token: str) -> None:
        await self._queue.put(token)

    async def fail(self, exc: BaseException) -> None:
        await self._queue.put(exc)

    async def finish(self) -> None:
        await self._queue.put(None)


@dataclass
class _CompletionJob:
    request: CompletionRequest
    priority: CompletionPriority
    slot_hint: int | None
    handle: CompletionHandle
    hold_slot: bool = False


@dataclass(order=True)
class _QueueItem:
    priority: int
    sequence: int
    job: _CompletionJob = field(compare=False)


class EnginePool:
    def __init__(
        self,
        *,
        base_url: str,
        parallel_slots: int,
        completion_client: CompletionClient | None = None,
    ) -> None:
        if parallel_slots < 1:
            raise ValueError("parallel_slots must be >= 1")
        self.base_url = base_url
        self.parallel_slots = parallel_slots
        self._completion_client = completion_client or LlamaCompletionClient()
        self._queue: asyncio.PriorityQueue[_QueueItem] = asyncio.PriorityQueue()
        self._sequence = 0
        self._busy_slots: set[int] = set()
        self._task_slots: dict[str, int] = {}
        self._slot_condition = asyncio.Condition()
        self._dispatcher_task: asyncio.Task[None] | None = None
        self._job_tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    def start(self) -> None:
        if self._dispatcher_task is None:
            self._dispatcher_task = asyncio.create_task(
                self._dispatcher(),
                name="engine-dispatcher",
            )
            log.info("engine_pool.ready", slots=self.parallel_slots, base_url=self.base_url)

    async def close(self) -> None:
        self._closed = True
        if self._dispatcher_task is not None:
            self._dispatcher_task.cancel()
            await asyncio.gather(self._dispatcher_task, return_exceptions=True)
            self._dispatcher_task = None

        for task in tuple(self._job_tasks):
            task.cancel()
        if self._job_tasks:
            await asyncio.gather(*self._job_tasks, return_exceptions=True)
        log.info("engine_pool.closed")

    async def submit(
        self,
        request: CompletionRequest,
        priority: CompletionPriority,
        slot_hint: int | None = None,
    ) -> CompletionHandle:
        if self._closed:
            raise RuntimeError("EnginePool is closed")
        if self._dispatcher_task is None:
            self.start()
        if slot_hint is not None:
            self._validate_slot(slot_hint)

        handle = CompletionHandle(request)
        job = _CompletionJob(
            request=request,
            priority=priority,
            slot_hint=slot_hint,
            handle=handle,
        )
        self._sequence += 1
        await self._queue.put(_QueueItem(int(priority), self._sequence, job))
        return handle

    async def submit_assigned(
        self,
        task_id: str,
        request: CompletionRequest,
        priority: CompletionPriority = CompletionPriority.P1_SUBAGENT,
    ) -> CompletionHandle:
        """Run a completion on a task's reserved slot without releasing it after."""
        slot_id = self._task_slots.get(task_id)
        if slot_id is None:
            raise RuntimeError(f"No slot assigned for task_id={task_id}")
        if self._closed:
            raise RuntimeError("EnginePool is closed")
        if self._dispatcher_task is None:
            self.start()

        handle = CompletionHandle(request)
        job = _CompletionJob(
            request=request,
            priority=priority,
            slot_hint=slot_id,
            handle=handle,
            hold_slot=True,
        )
        self._sequence += 1
        await self._queue.put(_QueueItem(int(priority), self._sequence, job))
        return handle

    async def cancel(self, handle: CompletionHandle) -> None:
        handle.cancelled = True
        await handle.finish()

    async def reserve_slot(self, role: str, task_id: str | None = None) -> int:
        preferred = 0 if role == "main" else None
        slot_id = await self._claim_slot(preferred)
        log.debug("engine_slot.reserved", role=role, task_id=task_id, slot_id=slot_id)
        return slot_id

    async def release_slot(self, slot_id: int) -> None:
        self._validate_slot(slot_id)
        async with self._slot_condition:
            self._busy_slots.discard(slot_id)
            self._slot_condition.notify_all()
        log.debug("engine_slot.released", slot_id=slot_id)

    async def assign_slot(self, task_id: str, role: str = "subagent") -> int:
        """Reserve a slot and track it by task_id until free_slot(task_id). Slot 0 = Main only."""
        async with self._slot_condition:
            while True:
                if role == "main":
                    candidates = [0]
                else:
                    candidates = list(range(1, self.parallel_slots)) + [
                        s
                        for s in range(self.parallel_slots)
                        if s != 0
                    ]
                for slot_id in candidates:
                    if slot_id not in self._busy_slots:
                        self._busy_slots.add(slot_id)
                        self._task_slots[task_id] = slot_id
                        self._slot_condition.notify_all()
                        log.debug(
                            "engine_slot.assigned",
                            task_id=task_id,
                            slot_id=slot_id,
                            role=role,
                        )
                        return slot_id
                await self._slot_condition.wait()

    async def free_slot(self, task_id: str) -> None:
        slot_id = self._task_slots.pop(task_id, None)
        if slot_id is not None:
            await self.release_slot(slot_id)
            log.debug("engine_slot.freed", task_id=task_id, slot_id=slot_id)

    def slot_for_task(self, task_id: str) -> int | None:
        return self._task_slots.get(task_id)

    async def _dispatcher(self) -> None:
        while True:
            item = await self._queue.get()
            slot_id = await self._claim_slot(item.job.slot_hint)
            item.job.handle.slot_id = slot_id
            task = asyncio.create_task(
                self._run_job(item.job, slot_id),
                name=f"engine-job-{item.job.handle.id}",
            )
            self._job_tasks.add(task)
            task.add_done_callback(self._job_tasks.discard)

    async def _run_job(self, job: _CompletionJob, slot_id: int) -> None:
        log.debug(
            "engine_job.started",
            handle_id=job.handle.id,
            priority=job.priority.name,
            slot_id=slot_id,
        )
        try:
            async for token in self._completion_client.stream_completion(
                base_url=self.base_url,
                slot_id=slot_id,
                request=job.request,
            ):
                if job.handle.cancelled:
                    break
                await job.handle.put_token(token)
        except Exception as exc:
            await job.handle.fail(exc)
            log.error("engine_job.failed", handle_id=job.handle.id, slot_id=slot_id, error=str(exc))
        finally:
            if not job.hold_slot:
                await self.release_slot(slot_id)
            await job.handle.finish()
            log.debug("engine_job.finished", handle_id=job.handle.id, slot_id=slot_id)

    async def _claim_slot(self, slot_hint: int | None) -> int:
        async with self._slot_condition:
            while True:
                slot_id = self._available_slot(slot_hint)
                if slot_id is not None:
                    if slot_id not in self._busy_slots:
                        self._busy_slots.add(slot_id)
                    return slot_id
                await self._slot_condition.wait()

    def _available_slot(self, slot_hint: int | None) -> int | None:
        if slot_hint is not None:
            self._validate_slot(slot_hint)
            if slot_hint not in self._busy_slots:
                return slot_hint
            if slot_hint in self._task_slots.values():
                return slot_hint
            return None

        for slot_id in range(self.parallel_slots):
            if slot_id not in self._busy_slots:
                return slot_id
        return None

    def _validate_slot(self, slot_id: int) -> None:
        if slot_id < 0 or slot_id >= self.parallel_slots:
            raise ValueError(f"slot_id must be in range 0..{self.parallel_slots - 1}")


_engine_pool: EnginePool | None = None


def init_engine_pool(*, base_url: str, parallel_slots: int) -> EnginePool:
    global _engine_pool
    _engine_pool = EnginePool(base_url=base_url, parallel_slots=parallel_slots)
    _engine_pool.start()
    return _engine_pool


def get_engine_pool() -> EnginePool:
    if _engine_pool is None:
        raise RuntimeError("Engine pool not initialized")
    return _engine_pool


async def close_engine_pool() -> None:
    global _engine_pool
    if _engine_pool is not None:
        await _engine_pool.close()
        _engine_pool = None


async def submit(
    request: CompletionRequest,
    priority: CompletionPriority,
    slot_hint: int | None = None,
) -> CompletionHandle:
    return await get_engine_pool().submit(request, priority, slot_hint)


async def cancel(handle: CompletionHandle) -> None:
    await get_engine_pool().cancel(handle)


async def reserve_slot(role: str, task_id: str | None = None) -> int:
    return await get_engine_pool().reserve_slot(role, task_id)


async def release_slot(slot_id: int) -> None:
    await get_engine_pool().release_slot(slot_id)


def parse_completion_stream_line(line: str) -> str | None:
    raw = line.strip()
    if not raw:
        return None
    if raw.startswith("data:"):
        raw = raw.removeprefix("data:").strip()
    if raw == "[DONE]":
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    content = data.get("content")
    if isinstance(content, str):
        return content

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            delta = first.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                return str(delta["content"])
            if isinstance(first.get("text"), str):
                return str(first["text"])

    return None
