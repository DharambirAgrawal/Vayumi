from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator

from starlette.websockets import WebSocket

from server.engine.pool import EnginePool
from server.logger import get_logger
from server.orchestrator.supervisor import Supervisor
from server.transport.client_control import send_tts_play_control
from server.transport.protocol import (
    CaptionMessage,
    CaptionPayload,
    ServerAudioEndMessage,
    ServerAudioEndPayload,
    ServerAudioStartMessage,
    ServerAudioStartPayload,
)
from server.transport.ws import send_audio_frame, send_json
from server.voice.interrupt import InterruptController
from server.voice.stt.groq import GroqWhisper
from server.voice.tts.kokoro import KokoroTTS
from server.voice.types import TranscriptEvent

log = get_logger("voice.turn")

SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


async def run_voice_turn(
    *,
    websocket: WebSocket,
    engine_pool: EnginePool,
    stt: GroqWhisper,
    tts: KokoroTTS,
    interrupt: InterruptController,
    pcm_chunks: list[bytes],
    user_id: str,
    session_id: str,
    supervisor: Supervisor,
) -> None:
    if interrupt.should_drop_utterance():
        log.debug("voice_turn.dropped", user_id=user_id)
        return

    turn_id = str(uuid.uuid4())
    interrupt.begin_thinking(turn_id)

    async def chunk_iter() -> AsyncIterator[bytes]:
        for chunk in pcm_chunks:
            yield chunk

    transcript = ""
    async for event in stt.transcribe_stream(chunk_iter()):
        if isinstance(event, TranscriptEvent):
            transcript = event.text

    transcript = transcript.strip()
    if not transcript:
        interrupt.finish_turn()
        log.debug("voice_turn.empty_transcript", user_id=user_id)
        return

    log.info("voice_turn.transcript", user_id=user_id, turn_id=turn_id, text=transcript)

    async def on_token(token: str) -> None:
        if interrupt.tts_cancelled():
            return
        await send_json(
            websocket,
            CaptionMessage(payload=CaptionPayload(text=token, partial=True)),
        )

    try:
        output = await supervisor.run_turn(
            transcript,
            engine_pool=engine_pool,
            on_token=on_token,
        )
        assistant_text = output.assistant_text.strip()

        if assistant_text and not interrupt.tts_cancelled():
            await _begin_tts_stream(websocket, turn_id=turn_id, interrupt=interrupt)
            await _speak_text(
                websocket=websocket,
                tts=tts,
                text=assistant_text,
                interrupt=interrupt,
            )
            if not interrupt.tts_cancelled():
                await send_json(
                    websocket,
                    ServerAudioEndMessage(payload=ServerAudioEndPayload(turn_id=turn_id)),
                )

        await send_json(
            websocket,
            CaptionMessage(payload=CaptionPayload(text=assistant_text, partial=False)),
        )
    except asyncio.CancelledError:
        log.info("voice_turn.cancelled", user_id=user_id, turn_id=turn_id)
        raise
    except Exception as exc:
        log.error("voice_turn.failed", user_id=user_id, turn_id=turn_id, error=str(exc))
        raise
    finally:
        interrupt.finish_turn()


async def _begin_tts_stream(
    websocket: WebSocket,
    *,
    turn_id: str,
    interrupt: InterruptController,
) -> None:
    await send_json(
        websocket,
        ServerAudioStartMessage(payload=ServerAudioStartPayload(turn_id=turn_id)),
    )
    await send_tts_play_control(websocket, turn_id=turn_id)
    interrupt.begin_speaking()


async def _speak_text(
    *,
    websocket: WebSocket,
    tts: KokoroTTS,
    text: str,
    interrupt: InterruptController,
) -> None:
    sentences = SENTENCE_BOUNDARY_RE.split(text)
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if interrupt.tts_cancelled():
            break
        async for frame in tts.synthesize_stream(sentence):
            if interrupt.tts_cancelled():
                break
            await send_audio_frame(websocket, frame.pcm)
