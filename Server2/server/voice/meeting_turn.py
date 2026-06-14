from __future__ import annotations

import asyncio
import uuid

from starlette.websockets import WebSocket

from server.engine.pool import EnginePool
from server.logger import get_logger
from server.orchestrator.meeting import handle_meeting_transcript
from server.transport.session_registry import UserSession
from server.voice.stt.base import STTBackend
from server.voice.stt_pipeline import transcribe_pcm_chunks

log = get_logger("voice.meeting_turn")


async def run_meeting_turn(
    *,
    websocket: WebSocket,
    engine_pool: EnginePool,
    stt: STTBackend,
    user_session: UserSession,
    pcm_chunks: list[bytes],
) -> None:
    """STT in meeting mode — passive accumulation or addressed Main turn."""
    interrupt = user_session.interrupt

    if interrupt.should_drop_utterance():
        log.debug("meeting_turn.dropped", user_id=user_session.user_id)
        return

    turn_id = str(uuid.uuid4())
    transcript = await transcribe_pcm_chunks(stt, pcm_chunks)
    if transcript is None:
        log.debug(
            "meeting_turn.no_transcript",
            user_id=user_session.user_id,
            bytes=sum(len(c) for c in pcm_chunks),
        )
        return

    log.info(
        "meeting_turn.transcript",
        user_id=user_session.user_id,
        turn_id=turn_id,
        text=transcript,
    )

    settings = websocket.app.state.settings
    try:
        await handle_meeting_transcript(
            user_session,
            transcript,
            websocket,
            engine_pool,
            turn_id,
            settings,
        )
    except asyncio.CancelledError:
        log.info(
            "meeting_turn.cancelled",
            user_id=user_session.user_id,
            turn_id=turn_id,
        )
        raise
    except Exception as exc:
        log.error(
            "meeting_turn.failed",
            user_id=user_session.user_id,
            turn_id=turn_id,
            error=str(exc),
        )
        raise
