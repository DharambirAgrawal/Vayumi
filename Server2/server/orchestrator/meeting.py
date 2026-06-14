from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from starlette.websockets import WebSocket

from server.config import get_settings
from server.logger import get_logger
from server.memory.meeting_storage import store_meeting_chunk
from server.transport.client_control import send_client_control
from server.transport.outbound import send_json
from server.transport.protocol import CaptionMessage, CaptionPayload, EventMessage, EventPayload

if TYPE_CHECKING:
    from server.engine.pool import EnginePool
    from server.transport.session_registry import UserSession

log = get_logger("orchestrator.meeting")

_ADDRESS_PREFIXES = (
    "hey vayumi",
    "hey, vayumi",
    "vayumi,",
    "vayumi ",
)

_START_MEETING_RE = re.compile(
    r"\b(?:start|begin|enter)\s+(?:a\s+)?meeting(?:\s+mode)?\b",
    re.IGNORECASE,
)
_END_MEETING_RE = re.compile(
    r"\b(?:end|stop|exit|leave)\s+(?:the\s+)?meeting(?:\s+mode)?\b",
    re.IGNORECASE,
)


@dataclass
class MeetingUtterance:
    speaker: str
    text: str
    ts: float


@dataclass
class MeetingState:
    meeting_id: str
    started_at: float
    buffer: list[MeetingUtterance] = field(default_factory=list)
    last_utterance_at: float | None = None
    current_speaker: str = "SPEAKER_00"
    speaker_index: int = 0
    last_chunk_flush_at: float = field(default_factory=time.time)


def _new_meeting_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"


def is_addressed_transcript(text: str) -> tuple[bool, str]:
    """Return (addressed, stripped_text) for wake-phrase prefix match."""
    stripped = text.strip()
    if not stripped:
        return False, ""
    lower = stripped.lower()
    for prefix in _ADDRESS_PREFIXES:
        if lower.startswith(prefix):
            remainder = stripped[len(prefix) :].lstrip(" ,:;-")
            return True, remainder
    return False, stripped


def parse_mode_command(text: str) -> Literal["start", "end"] | None:
    """Parse start/end meeting commands from addressed transcript text."""
    if _END_MEETING_RE.search(text):
        return "end"
    if _START_MEETING_RE.search(text):
        return "start"
    return None


def _next_speaker(state: MeetingState) -> str:
    state.speaker_index += 1
    state.current_speaker = f"SPEAKER_{state.speaker_index:02d}"
    return state.current_speaker


def _assign_speaker(state: MeetingState, now: float) -> str:
    settings = get_settings()
    gap = settings.meeting_speaker_gap_seconds
    if (
        state.last_utterance_at is not None
        and now - state.last_utterance_at >= gap
    ):
        return _next_speaker(state)
    return state.current_speaker


def _buffer_text(state: MeetingState) -> str:
    return "\n".join(f"{u.speaker}: {u.text}" for u in state.buffer)


async def _emit_meeting_caption(
    websocket: WebSocket,
    *,
    turn_id: str,
    speaker: str,
    text: str,
) -> None:
    await send_json(
        websocket,
        CaptionMessage(
            payload=CaptionPayload(
                text=f"{speaker}: {text}",
                partial=False,
                turn_id=turn_id,
            ),
        ),
    )


async def _emit_meeting_event(
    websocket: WebSocket,
    *,
    kind: str,
    meeting_id: str,
) -> None:
    await send_json(
        websocket,
        EventMessage(
            payload=EventPayload(
                kind=kind,
                summary=f"Meeting {meeting_id}",
            ),
        ),
    )


async def append_utterance(
    session: UserSession,
    *,
    text: str,
    websocket: WebSocket,
    turn_id: str,
) -> None:
    state = session.meeting_state
    if state is None:
        return

    now = time.time()
    speaker = _assign_speaker(state, now)
    state.last_utterance_at = now
    state.buffer.append(MeetingUtterance(speaker=speaker, text=text, ts=now))
    await _emit_meeting_caption(
        websocket, turn_id=turn_id, speaker=speaker, text=text
    )
    await maybe_flush_chunk(session)


async def maybe_flush_chunk(session: UserSession) -> None:
    state = session.meeting_state
    if state is None or not state.buffer:
        return

    settings = get_settings()
    now = time.time()
    if now - state.last_chunk_flush_at < settings.meeting_chunk_interval_seconds:
        return

    await _flush_buffer(session)


async def _flush_buffer(session: UserSession) -> None:
    state = session.meeting_state
    if state is None or not state.buffer:
        return

    text = _buffer_text(state)
    ts_start = state.buffer[0].ts
    ts_end = state.buffer[-1].ts
    speakers = {u.speaker for u in state.buffer}
    speaker = "MIXED" if len(speakers) > 1 else state.buffer[0].speaker
    chunk_id = str(uuid.uuid4())

    await store_meeting_chunk(
        chunk_id=chunk_id,
        meeting_id=state.meeting_id,
        user_id=session.user_id,
        speaker=speaker,
        ts_start=ts_start,
        ts_end=ts_end,
        text=text,
    )

    state.buffer.clear()
    state.last_chunk_flush_at = time.time()
    log.info(
        "meeting.chunk_flushed",
        user_id=session.user_id,
        meeting_id=state.meeting_id,
        chunk_id=chunk_id,
        chars=len(text),
    )


async def finalize_meeting(
    session: UserSession,
    engine_pool: EnginePool,
) -> MeetingState | None:
    """Flush remaining buffer and schedule post-meeting summary."""
    state = session.meeting_state
    if state is None:
        return None

    if state.buffer:
        await _flush_buffer(session)

    ended_at = time.time()
    meeting_id = state.meeting_id
    started_at = state.started_at
    session.meeting_state = None

    from server.memory.meeting_summarizer import schedule_post_meeting_summary

    schedule_post_meeting_summary(
        meeting_id=meeting_id,
        user_id=session.user_id,
        started_at=started_at,
        ended_at=ended_at,
        engine_pool=engine_pool,
    )
    log.info(
        "meeting.finalized",
        user_id=session.user_id,
        meeting_id=meeting_id,
    )
    return state


async def enter_meeting_mode(
    session: UserSession,
    websocket: WebSocket,
) -> str:
    meeting_id = _new_meeting_id()
    now = time.time()
    session.meeting_state = MeetingState(
        meeting_id=meeting_id,
        started_at=now,
        last_chunk_flush_at=now,
    )
    session.client_control.set_mode("meeting")
    await send_client_control(websocket, "start_capture", "meeting_started")
    await _emit_meeting_event(websocket, kind="meeting_started", meeting_id=meeting_id)
    log.info(
        "meeting.started",
        user_id=session.user_id,
        meeting_id=meeting_id,
    )
    return meeting_id


async def exit_meeting_mode(
    session: UserSession,
    websocket: WebSocket,
    engine_pool: EnginePool,
) -> None:
    state = await finalize_meeting(session, engine_pool)
    session.client_control.set_mode("conversation")
    meeting_id = state.meeting_id if state else ""
    await _emit_meeting_event(websocket, kind="meeting_ended", meeting_id=meeting_id)
    log.info("meeting.ended", user_id=session.user_id, meeting_id=meeting_id)


async def on_mode_change(
    session: UserSession,
    new_mode: Literal["conversation", "meeting"],
    websocket: WebSocket,
    engine_pool: EnginePool,
) -> None:
    old_mode = session.client_control.mode
    if old_mode == new_mode:
        return

    if new_mode == "meeting":
        await enter_meeting_mode(session, websocket)
        return

    if old_mode == "meeting":
        await exit_meeting_mode(session, websocket, engine_pool)
        return

    session.client_control.set_mode(new_mode)


async def handle_meeting_transcript(
    session: UserSession,
    transcript: str,
    websocket: WebSocket,
    engine_pool: EnginePool,
    turn_id: str,
    settings: object,
) -> None:
    """Route passive accumulation vs addressed Main turn vs mode commands."""
    from server.transport.turn_coordinator import run_supervisor_text_turn

    addressed, body = is_addressed_transcript(transcript)
    if addressed:
        command = parse_mode_command(body)
        if command == "end":
            await exit_meeting_mode(session, websocket, engine_pool)
            return
        if command == "start":
            if session.meeting_state is None:
                await enter_meeting_mode(session, websocket)
            return

        query = body.strip()
        if not query:
            return

        await run_supervisor_text_turn(
            websocket,
            session,
            query,
            settings,  # type: ignore[arg-type]
            engine_pool,
            input_kind="voice",
            computed_respond_via="chat_only",
            turn_id=turn_id,
            interrupt_policy="replace",
        )
        return

    await append_utterance(
        session,
        text=transcript,
        websocket=websocket,
        turn_id=turn_id,
    )
