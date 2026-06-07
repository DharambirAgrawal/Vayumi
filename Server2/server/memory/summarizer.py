from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from server.config import get_settings
from server.engine.pool import CompletionPriority, CompletionRequest, EnginePool
from server.engine.prompt import SummarizerPromptContext, build_summarizer_chat_messages
from server.logger import get_logger
from server.memory import facts
from server.memory.session import (
    TurnRecord,
    compressed_history,
    estimate_history_tokens,
    prune_turns,
    turns_for_summarization,
    update_compressed_summary,
)
from server.memory.warm import affects_warm_profile

log = get_logger("memory.summarizer")

_session_locks: dict[str, asyncio.Lock] = {}
_background_tasks: set[asyncio.Task[None]] = set()

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


class ExtractedFact(BaseModel):
    key: str
    value: Any
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)


class SummarizerOutput(BaseModel):
    summary: str
    facts: list[ExtractedFact] = Field(default_factory=list)


def _session_lock(session_id: str) -> asyncio.Lock:
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
    return lock


def _summarizer_slot_hint(parallel_slots: int) -> int:
    return max(0, parallel_slots - 1)


def _turn_to_line(turn: TurnRecord) -> str:
    role = turn.role.strip().lower() or "user"
    return f"{role}: {turn.text.strip()}"


def _parse_summarizer_json(raw: str) -> SummarizerOutput | None:
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
        return SummarizerOutput.model_validate(payload)
    except ValidationError:
        return None


async def _call_summarizer_llm(
    *,
    engine_pool: EnginePool,
    messages: list[dict[str, str]],
) -> str:
    settings = get_settings()
    slot_hint = _summarizer_slot_hint(settings.llama_parallel_slots)
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


async def _persist_extracted_facts(
    user_id: str,
    extracted: list[ExtractedFact],
    *,
    source: str,
) -> int:
    settings = get_settings()
    written = 0
    for item in extracted:
        key = item.key.strip()
        if not key:
            continue
        if item.confidence < settings.summarizer_min_fact_confidence:
            log.debug(
                "summarizer.fact_skipped_low_confidence",
                user_id=user_id,
                key=key,
                confidence=item.confidence,
            )
            continue
        try:
            await facts.set_fact(user_id, key, item.value, source)
            written += 1
        except Exception as exc:
            log.warning(
                "summarizer.fact_write_failed",
                user_id=user_id,
                key=key,
                error=str(exc),
            )
    return written


async def summarize_session(
    session_id: str,
    user_id: str,
    *,
    engine_pool: EnginePool,
) -> bool:
    """
    Compress older turns into sessions.compressed_summary and extract profile facts.
    Returns True when a compression pass completed successfully.
    """
    settings = get_settings()
    turns = await turns_for_summarization(
        session_id,
        keep_recent=settings.summarizer_recent_turn_keep,
    )
    if not turns:
        log.debug("summarizer.skip_no_old_turns", session_id=session_id)
        return False

    existing = await compressed_history(session_id)
    messages = build_summarizer_chat_messages(
        SummarizerPromptContext(
            existing_summary=existing,
            turn_lines=[_turn_to_line(turn) for turn in turns],
        )
    )

    settings = get_settings()
    raw = ""
    last_error: str | None = None
    for attempt in range(settings.summarizer_max_retries + 1):
        try:
            raw = await _call_summarizer_llm(engine_pool=engine_pool, messages=messages)
            parsed = _parse_summarizer_json(raw)
            if parsed is None:
                last_error = "invalid_json"
                log.warning(
                    "summarizer.invalid_json",
                    session_id=session_id,
                    attempt=attempt,
                    preview=raw[:200],
                )
                if attempt < settings.summarizer_max_retries:
                    await asyncio.sleep(
                        settings.summarizer_retry_base_seconds * (2**attempt)
                    )
                continue

            summary = parsed.summary.strip()
            if not summary:
                last_error = "empty_summary"
                log.warning("summarizer.empty_summary", session_id=session_id)
                return False

            await update_compressed_summary(session_id, summary)
            fact_count = await _persist_extracted_facts(
                user_id,
                parsed.facts,
                source="summarizer",
            )
            pruned = await prune_turns(session_id, [turn.id for turn in turns])
            log.info(
                "summarizer.session_done",
                session_id=session_id,
                user_id=user_id,
                facts_written=fact_count,
                turns_pruned=pruned,
                profile_facts=sum(
                    1 for f in parsed.facts if affects_warm_profile(f.key.strip())
                ),
            )
            return True
        except Exception as exc:
            last_error = str(exc)
            log.warning(
                "summarizer.llm_failed",
                session_id=session_id,
                attempt=attempt,
                error=str(exc),
            )
            if attempt < settings.summarizer_max_retries:
                await asyncio.sleep(
                    settings.summarizer_retry_base_seconds * (2**attempt)
                )

    log.error(
        "summarizer.session_gave_up",
        session_id=session_id,
        user_id=user_id,
        last_error=last_error,
    )
    return False


def _normalize_facts_payload(payload: object) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("facts", "facts_to_persist"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


async def extract_facts_from_task(
    task_id: str,
    user_id: str,
    facts_payload: object,
) -> int:
    """
    Persist structured facts from a sub-agent DONE payload.
    No LLM — Pydantic validation only.
    """
    raw_items = _normalize_facts_payload(facts_payload)
    if not raw_items:
        return 0

    source = f"task:{task_id}"
    written = 0
    for raw in raw_items:
        try:
            item = ExtractedFact.model_validate(raw)
        except ValidationError as exc:
            log.warning(
                "summarizer.task_fact_invalid",
                task_id=task_id,
                error=str(exc),
                raw=raw,
            )
            continue
        key = item.key.strip()
        if not key:
            continue
        if item.confidence < get_settings().summarizer_min_fact_confidence:
            continue
        try:
            await facts.set_fact(user_id, key, item.value, source)
            written += 1
        except Exception as exc:
            log.warning(
                "summarizer.task_fact_write_failed",
                task_id=task_id,
                key=key,
                error=str(exc),
            )
    if written:
        log.info(
            "summarizer.task_facts_persisted",
            task_id=task_id,
            user_id=user_id,
            count=written,
        )
    return written


async def _maybe_summarize_session(
    session_id: str,
    user_id: str,
    engine_pool: EnginePool,
) -> None:
    settings = get_settings()
    lock = _session_lock(session_id)
    if lock.locked():
        log.debug("summarizer.skip_inflight", session_id=session_id)
        return

    async with lock:
        try:
            tokens = await estimate_history_tokens(session_id)
            if tokens < settings.summarizer_token_threshold:
                return
            await summarize_session(session_id, user_id, engine_pool=engine_pool)
        except Exception as exc:
            log.error(
                "summarizer.background_failed",
                session_id=session_id,
                user_id=user_id,
                error=str(exc),
            )


def _track_background_task(task: asyncio.Task[None]) -> None:
    _background_tasks.add(task)

    def _done(t: asyncio.Task[None]) -> None:
        _background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            log.error("summarizer.background_task_crashed", error=str(exc))

    task.add_done_callback(_done)


def schedule_session_summarization(
    *,
    session_id: str,
    user_id: str,
    engine_pool: EnginePool,
) -> None:
    """
    Fire-and-forget background compression check. Never blocks the user turn path.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("summarizer.schedule_no_loop", session_id=session_id)
        return

    task = loop.create_task(
        _maybe_summarize_session(session_id, user_id, engine_pool),
        name=f"summarize-{session_id[:8]}",
    )
    _track_background_task(task)


def schedule_task_fact_extraction(
    *,
    task_id: str,
    user_id: str,
    facts_payload: object,
) -> None:
    """Fire-and-forget persistence of facts_to_persist from DONE signals."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _run() -> None:
        try:
            await extract_facts_from_task(task_id, user_id, facts_payload)
        except Exception as exc:
            log.error(
                "summarizer.task_extract_failed",
                task_id=task_id,
                error=str(exc),
            )

    task = loop.create_task(_run(), name=f"task-facts-{task_id[:8]}")
    _track_background_task(task)
