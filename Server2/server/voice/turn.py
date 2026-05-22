from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

from starlette.websockets import WebSocket

from server.engine.pool import EnginePool
from server.logger import get_logger
from server.orchestrator.supervisor import TurnInput
from server.transport.session_registry import UserSession
from server.transport.turn_coordinator import drain_pending_voice, persist_interrupted_assistant
from server.voice.captions import make_streaming_caption_handler
from server.voice.delivery import deliver_turn_output, deliver_user_message
from server.voice.respond_via import compute_respond_via
from server.voice.streaming_tts import StreamingTtsPipeline, make_on_token_with_streaming_tts
from server.voice.stt.groq import GroqWhisper
from server.voice.transcript import is_meaningful_transcript, voice_pcm_is_viable
from server.voice.tts.kokoro import KokoroTTS
from server.voice.types import TranscriptEvent

log = get_logger("voice.turn")


async def run_voice_turn(
    *,
    websocket: WebSocket,
    engine_pool: EnginePool,
    stt: GroqWhisper,
    tts: KokoroTTS,
    user_session: UserSession,
    pcm_chunks: list[bytes],
    suppression_delay_ms: int,
) -> None:
    interrupt = user_session.interrupt
    supervisor = user_session.supervisor

    if interrupt.should_drop_utterance():
        log.debug("voice_turn.dropped", user_id=user_session.user_id)
        return

    if not voice_pcm_is_viable(pcm_chunks):
        log.debug(
            "voice_turn.audio_too_short",
            user_id=user_session.user_id,
            bytes=sum(len(c) for c in pcm_chunks),
        )
        return

    turn_id = str(uuid.uuid4())
    interrupt.begin_thinking(turn_id)
    user_session.turn_llm_persisted = False
    streamed_assistant = ""

    async def chunk_iter() -> AsyncIterator[bytes]:
        for chunk in pcm_chunks:
            yield chunk

    transcript = ""
    async for event in stt.transcribe_stream(chunk_iter()):
        if isinstance(event, TranscriptEvent):
            transcript = event.text

    transcript = transcript.strip()
    if not is_meaningful_transcript(transcript):
        interrupt.finish_turn()
        log.debug(
            "voice_turn.junk_transcript",
            user_id=user_session.user_id,
            text=transcript,
        )
        return

    log.info(
        "voice_turn.transcript",
        user_id=user_session.user_id,
        turn_id=turn_id,
        text=transcript,
    )

    await deliver_user_message(
        websocket, turn_id=turn_id, text=transcript, source="voice"
    )

    decision = compute_respond_via(
        capabilities_tts=user_session.capabilities.get("tts", True),
        client_state=user_session.client_control,
        input_kind="voice",
    )

    pipeline: StreamingTtsPipeline | None = None
    if decision.respond_via == "voice_and_chat":
        pipeline = StreamingTtsPipeline(
            websocket=websocket,
            turn_id=turn_id,
            interrupt=interrupt,
            tts=tts,
            emit_sentence_captions=True,
        )
        await pipeline.start()

    def _accumulate_streamed(token: str) -> None:
        nonlocal streamed_assistant
        streamed_assistant += token

    on_token = make_on_token_with_streaming_tts(
        base_on_token=make_streaming_caption_handler(
            websocket=websocket,
            turn_id=turn_id,
            interrupt=interrupt,
            accumulate=_accumulate_streamed,
            emit_partial_captions=pipeline is None,
        ),
        pipeline=pipeline,
    )

    try:
        tool_runner = getattr(websocket.app.state, "tool_runner", None)
        from server.transport.ws import make_tool_event_emitter
        from server.voice.status_caption import send_status_caption

        async def on_status_caption(status: str) -> None:
            await send_status_caption(websocket, turn_id=turn_id, text=status)

        output = await supervisor.handle_turn(
            TurnInput(kind="voice", text=transcript),
            engine_pool=engine_pool,
            on_token=on_token,
            computed_respond_via=decision.respond_via,
            turn_id=turn_id,
            tool_runner=tool_runner,
            on_tool_event=make_tool_event_emitter(user_session),
            on_status_caption=on_status_caption,
        )
        user_session.turn_llm_persisted = True
        if pipeline is not None:
            await pipeline.flush()
            await pipeline.finish(suppression_delay_ms)
        await deliver_turn_output(
            websocket,
            turn_id=output.turn_id,
            assistant_text=output.assistant_text,
            respond_via=output.respond_via,
            interrupt=interrupt,
            tts=None,
            suppression_delay_ms=suppression_delay_ms,
            stream_captions_during_llm=True,
            tts_streamed_during_llm=pipeline is not None,
        )
    except asyncio.CancelledError:
        if pipeline is not None:
            await pipeline.cancel()
        if streamed_assistant.strip():
            await persist_interrupted_assistant(user_session, streamed_assistant)
        log.info("voice_turn.cancelled", user_id=user_session.user_id, turn_id=turn_id)
        raise
    except Exception as exc:
        log.error(
            "voice_turn.failed",
            user_id=user_session.user_id,
            turn_id=turn_id,
            error=str(exc),
        )
        raise
    finally:
        interrupt.finish_turn()
        from server.transport.chat_queue import drain_queued_chat
        from server.transport.ws import _run_chat_turn

        settings = websocket.app.state.settings
        await drain_queued_chat(
            user_session,
            websocket,
            engine_pool,
            run_chat_turn=_run_chat_turn,
        )
        await drain_pending_voice(websocket, user_session, settings)
