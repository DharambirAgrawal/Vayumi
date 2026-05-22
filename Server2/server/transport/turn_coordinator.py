from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from starlette.websockets import WebSocket

from server.logger import get_logger
from server.transport.session_registry import UserSession

if TYPE_CHECKING:
    from server.config import Settings
    from server.engine.pool import EnginePool

log = get_logger("transport.turn_coordinator")


def session_busy(session: UserSession) -> bool:
    return session.interrupt.state.value in ("speaking", "thinking")


async def persist_interrupted_assistant(
    session: UserSession,
    partial_text: str,
) -> None:
    """Save a cut-off assistant reply so the model sees it on the next turn."""
    text = partial_text.strip()
    if not text or session.turn_llm_persisted:
        return
    from server.memory.session import append_turn

    await append_turn(session.session_id, session.user_id, "assistant", text)
    session.turn_llm_persisted = True
    log.info(
        "turn.interrupted_assistant_persisted",
        user_id=session.user_id,
        chars=len(text),
    )


def defer_voice_utterance(session: UserSession, pcm_chunks: list[bytes]) -> None:
    from server.voice.transcript import voice_pcm_is_viable

    if not pcm_chunks or not voice_pcm_is_viable(pcm_chunks):
        return
    session.pending_voice_chunks = list(pcm_chunks)
    log.info(
        "voice.deferred",
        user_id=session.user_id,
        chunks=len(pcm_chunks),
        bytes=sum(len(c) for c in pcm_chunks),
    )


async def start_voice_turn(
    websocket: WebSocket,
    session: UserSession,
    settings: Settings,
    pcm_chunks: list[bytes],
) -> None:
    from server.voice.stt.groq import GroqWhisper
    from server.voice.turn import run_voice_turn

    voice = websocket.app.state.voice
    stt: GroqWhisper = voice["stt"]
    engine_pool: EnginePool = websocket.app.state.engine_pool
    delay = (
        settings.aec_client_suppression_delay_ms
        if session.capabilities.get("aec")
        else settings.self_echo_suppression_delay_ms
    )

    session.turn_task = asyncio.create_task(
        run_voice_turn(
            websocket=websocket,
            engine_pool=engine_pool,
            stt=stt,
            tts=voice["tts"],
            user_session=session,
            pcm_chunks=pcm_chunks,
            suppression_delay_ms=delay,
        ),
        name=f"voice-turn-{session.user_id}",
    )
    session.interrupt.attach_turn_task(session.turn_task)


async def drain_pending_voice(
    websocket: WebSocket,
    session: UserSession,
    settings: Settings,
) -> None:
    from server.voice.transcript import voice_pcm_is_viable

    chunks = session.pending_voice_chunks
    if not chunks:
        return
    if session.turn_task and not session.turn_task.done():
        return
    session.pending_voice_chunks = None
    if not voice_pcm_is_viable(chunks):
        log.debug(
            "voice.pending_discarded",
            user_id=session.user_id,
            bytes=sum(len(c) for c in chunks),
        )
        return
    await start_voice_turn(websocket, session, settings, chunks)
