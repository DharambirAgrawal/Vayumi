from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Protocol

import httpx

from server.logger import get_logger

log = get_logger("engine.pool")


class CompletionPriority(IntEnum):
    P0_MAIN = 0
    P1_SUBAGENT = 1
    P2_SUMMARIZER = 2


ChatMessage = dict[str, Any]


@dataclass(frozen=True)
class ParsedToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ChatCompletionResult:
    content: str
    tool_calls: list[ParsedToolCall]
    finish_reason: str | None = None


@dataclass(frozen=True)
class CompletionRequest:
    prompt: str | list[ChatMessage]
    max_tokens: int = 512
    temperature: float = 0.7
    stop: tuple[str, ...] = ()
    cache_prompt: bool = False
    stream: bool = True
    tools: list[dict[str, Any]] | None = None
    # When False, omit slot_id on the HTTP request so llama-server does not reuse
    # a poisoned per-slot KV cache (Gemma may EOS with empty content on slot 0).
    pin_slot: bool = True


class CompletionClient(Protocol):
    def stream_completion(
        self,
        *,
        base_url: str,
        slot_id: int | None,
        request: CompletionRequest,
    ) -> AsyncIterator[str]:
        ...

    async def complete_chat(
        self,
        *,
        base_url: str,
        slot_id: int | None,
        request: CompletionRequest,
    ) -> ChatCompletionResult:
        ...


class LlamaCompletionClient:
    def stream_completion(
        self,
        *,
        base_url: str,
        slot_id: int | None,
        request: CompletionRequest,
    ) -> AsyncIterator[str]:
        return self._stream_completion(base_url=base_url, slot_id=slot_id, request=request)

    async def complete_chat(
        self,
        *,
        base_url: str,
        slot_id: int | None,
        request: CompletionRequest,
    ) -> ChatCompletionResult:
        data = await self._fetch_completion_json(
            base_url=base_url,
            slot_id=slot_id,
            request=request,
        )
        return parse_chat_completion(data)

    @staticmethod
    def _completion_params(slot_id: int | None, request: CompletionRequest) -> dict[str, int]:
        if request.pin_slot and slot_id is not None:
            return {"slot_id": slot_id}
        return {}

    async def _stream_completion(
        self,
        *,
        base_url: str,
        slot_id: int | None,
        request: CompletionRequest,
    ) -> AsyncIterator[str]:
        if not request.stream:
            text = await self._fetch_completion_non_stream(
                base_url=base_url,
                slot_id=slot_id,
                request=request,
            )
            if text:
                yield text
            return

        emitted = False
        sample = ""
        payload: dict[str, object] = {
            "stream": True,
            "temperature": request.temperature,
            "cache_prompt": request.cache_prompt,
        }
        payload.update(self._chat_payload(request))
        if isinstance(request.prompt, list):
            endpoint = f"{base_url}/v1/chat/completions"
        else:
            endpoint = f"{base_url}/completion"

        query = self._completion_params(slot_id, request)
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                endpoint,
                params=query,
                json=payload,
                headers={"Accept": "text/event-stream"},
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    log.error(
                        "engine.completion_http_error",
                        endpoint=endpoint,
                        status=response.status_code,
                        body=body.decode(errors="replace")[:500],
                    )
                response.raise_for_status()
                buffer = ""
                async for chunk_text in response.aiter_text():
                    if not chunk_text:
                        continue
                    if len(sample) < 800:
                        remaining = 800 - len(sample)
                        sample += chunk_text[:remaining]
                    buffer += chunk_text
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        token = parse_completion_stream_line(line)
                        if token:
                            emitted = True
                            yield token
                tail = buffer.strip()
                if tail:
                    token = parse_completion_stream_line(tail)
                    if token:
                        emitted = True
                        yield token

        if not emitted:
            if sample:
                log.warning(
                    "engine.stream_empty",
                    slot_id=slot_id,
                    sample_len=len(sample),
                    sample=sample.replace("\n", "\\n")[:200],
                )
            fallback = await self._fetch_completion_non_stream(
                base_url=base_url,
                slot_id=slot_id,
                request=request,
            )
            if fallback:
                log.warning(
                    "engine.stream_empty_fallback",
                    slot_id=slot_id,
                    chars=len(fallback),
                )
                yield fallback

    @staticmethod
    def _chat_payload(request: CompletionRequest) -> dict[str, object]:
        payload: dict[str, object] = {}
        if isinstance(request.prompt, list):
            payload["messages"] = request.prompt
            payload["max_tokens"] = request.max_tokens
        else:
            payload["prompt"] = request.prompt
            payload["n_predict"] = request.max_tokens
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = "auto"
        if request.stop:
            payload["stop"] = list(request.stop)
        return payload

    async def _fetch_completion_json(
        self,
        *,
        base_url: str,
        slot_id: int | None,
        request: CompletionRequest,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "stream": False,
            "temperature": request.temperature,
            "cache_prompt": request.cache_prompt,
        }
        payload.update(self._chat_payload(request))
        if isinstance(request.prompt, list):
            endpoint = f"{base_url}/v1/chat/completions"
        else:
            endpoint = f"{base_url}/completion"

        query = self._completion_params(slot_id, request)
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                endpoint,
                params=query,
                json=payload,
            )
            if response.status_code >= 400:
                log.error(
                    "engine.completion_http_error",
                    endpoint=endpoint,
                    status=response.status_code,
                    body=response.text[:500],
                )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                return data
        return {}

    async def _fetch_completion_non_stream(
        self,
        *,
        base_url: str,
        slot_id: int | None,
        request: CompletionRequest,
    ) -> str:
        data = await self._fetch_completion_json(
            base_url=base_url,
            slot_id=slot_id,
            request=request,
        )
        return extract_completion_text(data)


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

    async def complete_chat(
        self,
        request: CompletionRequest,
        priority: CompletionPriority = CompletionPriority.P0_MAIN,
        slot_hint: int | None = None,
    ) -> ChatCompletionResult:
        """Non-streaming chat completion — used for native tool-calling turns."""
        if self._closed:
            raise RuntimeError("EnginePool is closed")
        if self._dispatcher_task is None:
            self.start()
        slot_id = await self._claim_slot(slot_hint)
        try:
            non_stream_request = CompletionRequest(
                prompt=request.prompt,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                stop=request.stop,
                cache_prompt=request.cache_prompt,
                stream=False,
                tools=request.tools,
                pin_slot=request.pin_slot,
            )
            complete_chat = getattr(self._completion_client, "complete_chat", None)
            if callable(complete_chat):
                return await complete_chat(
                    base_url=self.base_url,
                    slot_id=slot_id,
                    request=non_stream_request,
                )
            text = ""
            async for token in self._completion_client.stream_completion(
                base_url=self.base_url,
                slot_id=slot_id,
                request=non_stream_request,
            ):
                text += token
            return ChatCompletionResult(content=text, tool_calls=[])
        finally:
            await self.release_slot(slot_id)

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
                    candidates = list(range(1, self.parallel_slots))
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


def parse_chat_completion(data: dict[str, object]) -> ChatCompletionResult:
    """Parse llama-server /v1/chat/completions JSON into content + tool_calls."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ChatCompletionResult(content=extract_completion_text(data), tool_calls=[])

    first = choices[0]
    if not isinstance(first, dict):
        return ChatCompletionResult(content="", tool_calls=[])

    finish_reason = first.get("finish_reason")
    finish = finish_reason if isinstance(finish_reason, str) else None

    message = first.get("message")
    if not isinstance(message, dict):
        return ChatCompletionResult(content=extract_completion_text(data), tool_calls=[], finish_reason=finish)

    content_raw = message.get("content")
    content = content_raw if isinstance(content_raw, str) else ""

    tool_calls: list[ParsedToolCall] = []
    raw_calls = message.get("tool_calls")
    if isinstance(raw_calls, list):
        for index, item in enumerate(raw_calls):
            if not isinstance(item, dict):
                continue
            fn = item.get("function")
            if not isinstance(fn, dict):
                continue
            name = fn.get("name")
            args = fn.get("arguments")
            if not isinstance(name, str):
                continue
            call_id = item.get("id")
            if not isinstance(call_id, str) or not call_id:
                call_id = f"call_{index}"
            tool_calls.append(
                ParsedToolCall(
                    id=call_id,
                    name=name,
                    arguments=args if isinstance(args, str) else json.dumps(args or {}),
                )
            )

    return ChatCompletionResult(content=content, tool_calls=tool_calls, finish_reason=finish)


def tool_calls_to_openai_message(tool_calls: list[ParsedToolCall]) -> list[dict[str, object]]:
    return [
        {
            "id": call.id,
            "type": "function",
            "function": {"name": call.name, "arguments": call.arguments},
        }
        for call in tool_calls
    ]


def extract_completion_text(data: dict[str, object]) -> str:
    """Normalize llama-server / OpenAI-style completion JSON to plain text."""
    content = data.get("content")
    if isinstance(content, str) and content:
        return content

    text = data.get("text")
    if isinstance(text, str) and text:
        return text

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            if isinstance(first.get("text"), str) and first["text"]:
                return str(first["text"])
            message = first.get("message")
            if isinstance(message, dict):
                msg_content = message.get("content")
                if isinstance(msg_content, str) and msg_content:
                    return msg_content
            delta = first.get("delta")
            if isinstance(delta, dict):
                delta_content = delta.get("content")
                if isinstance(delta_content, str) and delta_content:
                    return str(delta_content)

    return ""


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
        return raw if raw else None

    if not isinstance(data, dict):
        return None

    piece = extract_completion_text(data)
    return piece if piece else None
