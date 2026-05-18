from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator

from starlette.websockets import WebSocket

from server.engine.pool import CompletionPriority, CompletionRequest, EnginePool
from server.engine.prompt import MainPromptContext, build_main_prompt
from server.logger import get_logger
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

SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s")


async def run_voice_turn(
    *,
    websocket: WebSocket,
    engine_pool: EnginePool,
    stt: GroqWhisper,
    tts: KokoroTTS,
    interrupt: InterruptController,
    pcm_chunks: list[bytes],
    user_id: str,
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

    prompt = build_main_prompt(MainPromptContext(user_text=transcript))
    request = CompletionRequest(prompt=prompt)
    handle = await engine_pool.submit(request, CompletionPriority.P0_MAIN, slot_hint=0)
    interrupt.attach_main_handle(handle)

    full_text = ""
    spoken_upto = 0
    audio_started = False

    try:
        async for token in handle:
            if interrupt.tts_cancelled():
                break
            full_text += token
            await send_json(
                websocket,
                CaptionMessage(payload=CaptionPayload(text=token, partial=True)),
            )

            boundary = _latest_sentence_end(full_text[spoken_upto:])
            if boundary is None:
                continue

            sentence_end = spoken_upto + boundary
            sentence = full_text[spoken_upto:sentence_end].strip()
            spoken_upto = sentence_end
            if not sentence:
                continue

            if not audio_started:
                await send_json(
                    websocket,
                    ServerAudioStartMessage(
                        payload=ServerAudioStartPayload(turn_id=turn_id),
                    ),
                )
                interrupt.begin_speaking()
                audio_started = True

            await _stream_tts(
                websocket=websocket,
                tts=tts,
                text=sentence,
                interrupt=interrupt,
            )

        remainder = full_text[spoken_upto:].strip()
        if remainder and not interrupt.tts_cancelled():
            if not audio_started:
                await send_json(
                    websocket,
                    ServerAudioStartMessage(
                        payload=ServerAudioStartPayload(turn_id=turn_id),
                    ),
                )
                interrupt.begin_speaking()
                audio_started = True
            await _stream_tts(
                websocket=websocket,
                tts=tts,
                text=remainder,
                interrupt=interrupt,
            )

        if audio_started and not interrupt.tts_cancelled():
            await send_json(
                websocket,
                ServerAudioEndMessage(payload=ServerAudioEndPayload(turn_id=turn_id)),
            )

        await send_json(
            websocket,
            CaptionMessage(payload=CaptionPayload(text=full_text, partial=False)),
        )
    except asyncio.CancelledError:
        log.info("voice_turn.cancelled", user_id=user_id, turn_id=turn_id)
        raise
    except Exception as exc:
        log.error("voice_turn.failed", user_id=user_id, turn_id=turn_id, error=str(exc))
        raise
    finally:
        interrupt.finish_turn()


async def _stream_tts(
    *,
    websocket: WebSocket,
    tts: KokoroTTS,
    text: str,
    interrupt: InterruptController,
) -> None:
    async for frame in tts.synthesize_stream(text):
        if interrupt.tts_cancelled():
            break
        await send_audio_frame(websocket, frame.pcm)


def _latest_sentence_end(segment: str) -> int | None:
    matches = list(SENTENCE_BOUNDARY_RE.finditer(segment))
    if not matches:
        return None
    return matches[-1].end()
