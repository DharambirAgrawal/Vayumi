from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from server.config import get_settings
from server.engine.pool import CompletionPriority, CompletionRequest, EnginePool
from server.engine.prompt import MeetingSummaryPromptContext, build_meeting_summary_chat_messages
from server.logger import get_logger
from server.memory import facts
from server.memory._background import (
    key_lock,
    parse_json_model,
    summarizer_slot_hint,
    track_background_task,
)
from server.memory.meeting_storage import list_meeting_chunks

log = get_logger("memory.meeting_summarizer")

_meeting_locks: dict[str, asyncio.Lock] = {}
_background_tasks: set[asyncio.Task[None]] = set()


class MeetingSummaryOutput(BaseModel):
    summary: str
    action_items: list[str] = Field(default_factory=list)


def _meeting_lock(meeting_id: str) -> asyncio.Lock:
    return key_lock(_meeting_locks, meeting_id)


def _parse_meeting_summary_json(raw: str) -> MeetingSummaryOutput | None:
    return parse_json_model(raw, MeetingSummaryOutput)


async def _call_meeting_summary_llm(
    *,
    engine_pool: EnginePool,
    messages: list[dict[str, str]],
) -> str:
    settings = get_settings()
    slot_hint = summarizer_slot_hint(settings.llama_parallel_slots)
    request = CompletionRequest(
        prompt=messages,
        max_tokens=1024,
        temperature=0.2,
        stream=False,
        pin_slot=False,
    )
    result = await engine_pool.complete_chat(
        request,
        priority=CompletionPriority.P2_SUMMARIZER,
        slot_hint=slot_hint,
    )
    return result.content.strip()


async def summarize_meeting(
    *,
    meeting_id: str,
    user_id: str,
    engine_pool: EnginePool,
) -> MeetingSummaryOutput | None:
    chunks = list_meeting_chunks(meeting_id, user_id)
    if not chunks:
        log.info("meeting_summarizer.no_chunks", meeting_id=meeting_id)
        return None

    transcript_lines = [chunk.text for chunk in chunks]
    messages = build_meeting_summary_chat_messages(
        MeetingSummaryPromptContext(transcript_lines=transcript_lines)
    )

    settings = get_settings()
    last_error: str | None = None
    for attempt in range(settings.meeting_summary_max_retries + 1):
        try:
            raw = await _call_meeting_summary_llm(
                engine_pool=engine_pool,
                messages=messages,
            )
            parsed = _parse_meeting_summary_json(raw)
            if parsed is not None:
                return parsed
            last_error = "invalid_json"
        except Exception as exc:
            last_error = str(exc)
            log.warning(
                "meeting_summarizer.attempt_failed",
                meeting_id=meeting_id,
                attempt=attempt,
                error=last_error,
            )
            if attempt < settings.meeting_summary_max_retries:
                await asyncio.sleep(
                    settings.summarizer_retry_base_seconds * (attempt + 1)
                )

    log.error(
        "meeting_summarizer.failed",
        meeting_id=meeting_id,
        error=last_error,
    )
    return None


async def _persist_meeting_summary(
    *,
    meeting_id: str,
    user_id: str,
    started_at: float,
    ended_at: float,
    output: MeetingSummaryOutput,
    chunk_count: int,
) -> None:
    key = f"meeting:{meeting_id}:summary"
    value = {
        "summary": output.summary,
        "action_items": output.action_items,
        "started_at": started_at,
        "ended_at": ended_at,
        "chunk_count": chunk_count,
        "meeting_id": meeting_id,
    }
    await facts.set_fact(user_id, key, value, "meeting_summarizer")
    log.info(
        "meeting_summarizer.persisted",
        user_id=user_id,
        meeting_id=meeting_id,
        key=key,
    )


async def _run_post_meeting_summary(
    *,
    meeting_id: str,
    user_id: str,
    started_at: float,
    ended_at: float,
    engine_pool: EnginePool,
) -> None:
    lock = _meeting_lock(meeting_id)
    if lock.locked():
        log.debug("meeting_summarizer.skip_inflight", meeting_id=meeting_id)
        return

    async with lock:
        try:
            output = await summarize_meeting(
                meeting_id=meeting_id,
                user_id=user_id,
                engine_pool=engine_pool,
            )
            if output is None:
                return
            chunks = list_meeting_chunks(meeting_id, user_id)
            await _persist_meeting_summary(
                meeting_id=meeting_id,
                user_id=user_id,
                started_at=started_at,
                ended_at=ended_at,
                output=output,
                chunk_count=len(chunks),
            )
        except Exception as exc:
            log.error(
                "meeting_summarizer.background_failed",
                meeting_id=meeting_id,
                user_id=user_id,
                error=str(exc),
            )


def _track_background_task(task: asyncio.Task[None]) -> None:
    track_background_task(
        _background_tasks,
        task,
        on_crash=lambda exc: log.error(
            "meeting_summarizer.background_task_crashed",
            error=str(exc),
        ),
    )


def schedule_post_meeting_summary(
    *,
    meeting_id: str,
    user_id: str,
    started_at: float,
    ended_at: float,
    engine_pool: EnginePool,
) -> None:
    """Fire-and-forget post-meeting summary. Never blocks the user path."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("meeting_summarizer.schedule_no_loop", meeting_id=meeting_id)
        return

    task = loop.create_task(
        _run_post_meeting_summary(
            meeting_id=meeting_id,
            user_id=user_id,
            started_at=started_at,
            ended_at=ended_at,
            engine_pool=engine_pool,
        ),
        name=f"meeting-summary-{meeting_id[:8]}",
    )
    _track_background_task(task)
