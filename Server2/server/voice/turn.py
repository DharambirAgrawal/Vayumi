from __future__ import annotations

import asyncio
import uuid

from starlette.websockets import WebSocket

from server.engine.pool import EnginePool
from server.logger import get_logger
from server.transport.session_registry import UserSession
from server.transport.turn_coordinator import run_supervisor_text_turn
from server.voice.delivery import deliver_user_message
from server.voice.respond_via import compute_respond_via
from server.voice.stt.base import STTBackend
from server.voice.stt_pipeline import transcribe_pcm_chunks

log = get_logger("voice.turn")


async def run_voice_turn(
    *,
    websocket: WebSocket,
    engine_pool: EnginePool,
    stt: STTBackend,
    user_session: UserSession,
    pcm_chunks: list[bytes],
) -> None:
    """STT then the same supervisor + TTS path as typed chat."""
    interrupt = user_session.interrupt

    if interrupt.should_drop_utterance():
        log.debug("voice_turn.dropped", user_id=user_session.user_id)
        return

    turn_id = str(uuid.uuid4())
    transcript = await transcribe_pcm_chunks(stt, pcm_chunks)
    if transcript is None:
        log.debug(
            "voice_turn.no_transcript",
            user_id=user_session.user_id,
            bytes=sum(len(c) for c in pcm_chunks),
        )
        return

    log.info(
        "voice_turn.transcript",
        user_id=user_session.user_id,
        turn_id=turn_id,
        text=transcript,
    )

    from server.orchestrator.meeting import (
        enter_meeting_mode,
        is_addressed_transcript,
        parse_mode_command,
    )

    addressed, body = is_addressed_transcript(transcript)
    if (
        addressed
        and user_session.client_control.mode == "conversation"
        and parse_mode_command(body) == "start"
    ):
        await enter_meeting_mode(user_session, websocket)
        return

    await deliver_user_message(
        websocket, turn_id=turn_id, text=transcript, source="voice"
    )

    decision = compute_respond_via(
        capabilities_tts=user_session.capabilities.get("tts", True),
        client_state=user_session.client_control,
        input_kind="voice",
    )

    settings = websocket.app.state.settings
    try:
        await run_supervisor_text_turn(
            websocket,
            user_session,
            transcript,
            settings,
            engine_pool,
            input_kind="voice",
            computed_respond_via=decision.respond_via,
            turn_id=turn_id,
            interrupt_policy=decision.interrupt_policy,
        )
    except asyncio.CancelledError:
        log.info(
            "voice_turn.cancelled",
            user_id=user_session.user_id,
            turn_id=turn_id,
        )
        raise
    except Exception as exc:
        log.error(
            "voice_turn.failed",
            user_id=user_session.user_id,
            turn_id=turn_id,
            error=str(exc),
        )
        raise
