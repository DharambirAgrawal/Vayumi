from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Literal

from starlette.websockets import WebSocket

from server.logger import get_logger
from server.orchestrator.directives import strip_directives
from server.transport.session_busy import session_busy
from server.transport.session_registry import UserSession
from server.voice.respond_via import InputKind, RespondVia, compute_respond_via

if TYPE_CHECKING:
    from server.config import Settings
    from server.engine.pool import EnginePool

log = get_logger("transport.turn_coordinator")


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
    from server.voice.stt.base import STTBackend
    from server.voice.turn import run_voice_turn

    voice = websocket.app.state.voice
    stt: STTBackend = voice["stt"]
    engine_pool: EnginePool = websocket.app.state.engine_pool

    session.turn_task = asyncio.create_task(
        run_voice_turn(
            websocket=websocket,
            engine_pool=engine_pool,
            stt=stt,
            user_session=session,
            pcm_chunks=pcm_chunks,
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


def suppression_delay_ms(session: UserSession, settings: Settings) -> int:
    if session.capabilities.get("aec"):
        return settings.aec_client_suppression_delay_ms
    return settings.self_echo_suppression_delay_ms


async def run_supervisor_text_turn(
    websocket: WebSocket,
    session: UserSession,
    text: str,
    settings: Settings,
    engine_pool: EnginePool,
    *,
    input_kind: InputKind = "chat",
    computed_respond_via: RespondVia | None = None,
    turn_id: str | None = None,
    allow_delegates: bool | None = None,
    injected_context: str = "",
    interrupt_policy: Literal["replace", "queue"] | None = None,
    force_voice: bool = False,
) -> None:
    """Shared chat/proactive turn delivery with streaming TTS and echo suppression."""
    from server.transport.ws import make_activity_event_emitter
    from server.voice.captions import make_streaming_caption_handler
    from server.voice.delivery import deliver_interrupted_partial, deliver_turn_output
    from server.voice.status_caption import make_status_caption_handler
    from server.voice.streaming_tts import StreamingTtsPipeline, make_on_token_with_streaming_tts

    tid = turn_id or str(uuid.uuid4())

    if computed_respond_via is None:
        decision = compute_respond_via(
            capabilities_tts=session.capabilities.get("tts", True),
            client_state=session.client_control,
            input_kind=input_kind,
            force_voice=force_voice,
        )
        respond_via = decision.respond_via
        policy = decision.interrupt_policy
    else:
        respond_via = computed_respond_via
        policy = interrupt_policy or "queue"

    log.info(
        "turn.chat_start",
        user_id=session.user_id,
        session_id=session.session_id,
        turn_id=tid,
        input_kind=input_kind,
        respond_via=respond_via,
        policy=policy,
    )

    if (
        session_busy(session)
        and policy == "queue"
        and input_kind != "proactive"
    ):
        from server.transport.chat_queue import enqueue_chat

        enqueue_chat(
            session,
            text,
            prefer_voice=force_voice or input_kind == "chat",
        )
        log.debug(
            "turn.requeued_busy",
            user_id=session.user_id,
            input_kind=input_kind,
        )
        return

    session.interrupt.begin_thinking(tid)
    session.accumulated_partial = ""
    session.turn_llm_persisted = False

    voice = websocket.app.state.voice
    use_streaming_tts = respond_via == "voice_and_chat"
    pipeline: StreamingTtsPipeline | None = None
    if use_streaming_tts:
        pipeline = StreamingTtsPipeline(
            websocket=websocket,
            turn_id=tid,
            interrupt=session.interrupt,
            tts=voice["tts"],
            emit_sentence_captions=True,
        )
        await pipeline.start()

    def _accumulate_partial(token: str) -> None:
        session.accumulated_partial += token

    on_token = make_on_token_with_streaming_tts(
        base_on_token=make_streaming_caption_handler(
            websocket=websocket,
            turn_id=tid,
            interrupt=session.interrupt,
            accumulate=_accumulate_partial,
            emit_partial_captions=not use_streaming_tts,
        ),
        pipeline=pipeline,
    )
    on_status_caption = make_status_caption_handler(
        websocket, turn_id=tid, pipeline=pipeline
    )

    try:
        tool_runner = getattr(websocket.app.state, "tool_runner", None)
        activity_emitter = make_activity_event_emitter(session)
        output = await session.supervisor.run_turn(
            text,
            engine_pool=engine_pool,
            on_token=on_token,
            input_kind=input_kind,
            computed_respond_via=respond_via,
            turn_id=tid,
            tool_runner=tool_runner,
            on_tool_event=activity_emitter,
            on_task_event=activity_emitter,
            on_status_caption=on_status_caption,
            allow_delegates=allow_delegates,
            injected_context=injected_context,
        )
        session.turn_llm_persisted = True
        delay = suppression_delay_ms(session, settings)
        delivery_pipeline = pipeline
        if output.revoice_final and pipeline is not None:
            from server.transport.client_control import send_client_control

            await pipeline.cancel()
            await send_client_control(
                websocket, "clear_queue", "answer_corrected", turn_id=tid
            )
            delivery_pipeline = None
            log.info(
                "turn.revoice_final",
                user_id=session.user_id,
                turn_id=tid,
            )
        elif pipeline is not None:
            await pipeline.flush()
            await pipeline.finish(delay)
        await deliver_turn_output(
            websocket,
            turn_id=output.turn_id,
            assistant_text=output.assistant_text,
            respond_via=output.respond_via,
            interrupt=session.interrupt,
            tts=voice["tts"],
            suppression_delay_ms=delay,
            stream_captions_during_llm=delivery_pipeline is not None,
            streaming_pipeline=delivery_pipeline,
        )
        log.info(
            "turn.chat_complete",
            user_id=session.user_id,
            session_id=session.session_id,
            turn_id=tid,
            respond_via=output.respond_via,
            chars=len(output.assistant_text),
        )
    except asyncio.CancelledError:
        if pipeline is not None:
            await pipeline.cancel()
        if session.accumulated_partial:
            cleaned_partial = strip_directives(session.accumulated_partial)
            await deliver_interrupted_partial(
                websocket,
                turn_id=tid,
                partial_text=cleaned_partial,
            )
            await persist_interrupted_assistant(session, cleaned_partial)
        raise
    except Exception as exc:
        from server.transport.outbound import send_json
        from server.transport.protocol import ErrorMessage, ErrorPayload

        log.error(
            "supervisor_text_turn.failed",
            user_id=session.user_id,
            input_kind=input_kind,
            error=str(exc),
        )
        err = ErrorMessage(payload=ErrorPayload(code=4500, message="Completion failed"))
        await send_json(websocket, err)
    finally:
        session.last_turn_completed_at = time.monotonic()
        session.interrupt.finish_turn()
        session.accumulated_partial = ""
        if input_kind in ("chat", "voice"):
            from server.transport.chat_queue import drain_queued_chat

            async def _run_chat_turn(
                ws, sess, chat_text, st, pool, *, force_voice: bool = False
            ):
                await run_supervisor_text_turn(
                    ws,
                    sess,
                    chat_text,
                    st,
                    pool,
                    input_kind="chat",
                    force_voice=force_voice,
                )

            await drain_queued_chat(
                session,
                websocket,
                engine_pool,
                run_chat_turn=_run_chat_turn,
            )
            await drain_pending_voice(websocket, session, settings)

