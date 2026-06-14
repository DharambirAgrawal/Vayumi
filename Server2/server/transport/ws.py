from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from server.auth import AuthError, verify_token
from server.logger import get_logger
from server.tools.runner import ToolEventEmitter, ToolRunner
from server.transport.client_control import send_client_control, send_interrupt_controls
from server.transport.outbound import send_json
from server.transport.protocol import (
    AudioEndMessage,
    AudioStartMessage,
    ChatMessage,
    ClientStateMessage,
    EchoMessage,
    EchoPayload,
    ErrorMessage,
    ErrorPayload,
    EventMessage,
    EventPayload,
    HelloMessage,
    InterruptMessage,
    ModeMessage,
    PingMessage,
    PongMessage,
    PongPayload,
    WelcomeMessage,
    WelcomePayload,
    parse_client_message,
)
from server.transport.session_registry import UserSession, enforce_session_singleton
from server.transport.session_busy import chat_should_queue, session_busy
from server.transport.turn_coordinator import (
    defer_voice_utterance,
    persist_interrupted_assistant,
    start_meeting_turn,
    start_voice_turn,
)
from server.voice.respond_via import compute_respond_via

if TYPE_CHECKING:
    from server.config import Settings
    from server.engine.pool import EnginePool

log = get_logger("transport.ws")


_ACTIVITY_EVENT_KINDS = frozenset(
    {
        "tool_started",
        "tool_done",
        "task_step",
        "task_done",
        "task_error",
    }
)


def make_tool_event_emitter(session: UserSession) -> ToolEventEmitter:
    return make_activity_event_emitter(session)  # type: ignore[return-value]


def make_activity_event_emitter(session: UserSession) -> ToolEventEmitter:
    async def emit(kind: str, task_id: str, summary: str) -> None:
        ws = session.websocket
        if ws is None or ws.client_state != WebSocketState.CONNECTED:
            return
        if kind not in _ACTIVITY_EVENT_KINDS:
            return
        msg = EventMessage(
            payload=EventPayload(
                kind=kind,  # type: ignore[arg-type]
                task_id=task_id,
                summary=summary,
            ),
        )
        await send_json(ws, msg)

    return emit  # type: ignore[return-value]


def _tool_runner(websocket: WebSocket) -> ToolRunner | None:
    return getattr(websocket.app.state, "tool_runner", None)


async def ws_endpoint(websocket: WebSocket) -> None:
    settings: Settings = websocket.app.state.settings

    token = websocket.query_params.get("token", "")
    if not token:
        await _close_auth_failed(websocket, code=4401, reason="Missing token")
        return

    try:
        token_payload = await verify_token(
            token,
            app_env=settings.app_env,
            jwt_public_key=settings.jwt_public_key,
        )
    except AuthError as e:
        log.warning("ws.auth_failed", error=e.message)
        await _close_auth_failed(websocket, code=e.code, reason=e.message)
        return

    await websocket.accept()
    log.info(
        "ws.connected",
        user_id=token_payload.user_id,
        session_id=token_payload.session_id,
    )

    session_holder: dict = {"session": None}

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                _inbound_loop(
                    websocket,
                    token_payload.user_id,
                    token_payload.session_id,
                    settings,
                    session_holder,
                )
            )
    except* WebSocketDisconnect:
        log.info("ws.disconnected", user_id=token_payload.user_id)
    except* Exception as eg:
        for exc in eg.exceptions:
            log.error("ws.error", error=str(exc), user_id=token_payload.user_id)
    finally:
        session = session_holder.get("session")
        if session and session.turn_task and not session.turn_task.done():
            session.turn_task.cancel()


async def _inbound_loop(
    websocket: WebSocket,
    user_id: str,
    jwt_session_id: str,
    settings: Settings,
    session_holder: dict,
) -> None:
    while True:
        message = await websocket.receive()
        msg_type = message.get("type", "")

        if msg_type == "websocket.disconnect":
            raise WebSocketDisconnect()

        if msg_type == "websocket.receive":
            if "text" in message and message["text"] is not None:
                raw = message["text"]
                if session_holder["session"] is None:
                    try:
                        msg = parse_client_message(raw)
                    except Exception as e:
                        err = ErrorMessage(
                            payload=ErrorPayload(code=4400, message=f"Invalid message: {e}")
                        )
                        await send_json(websocket, err)
                        await websocket.close(code=4400, reason="expected hello")
                        return
                    if not isinstance(msg, HelloMessage):
                        err = ErrorMessage(
                            payload=ErrorPayload(
                                code=4400, message="First message must be hello"
                            )
                        )
                        await send_json(websocket, err)
                        await websocket.close(code=4400, reason="expected hello")
                        return
                    session, resumed = await enforce_session_singleton(
                        user_id=user_id,
                        session_id=jwt_session_id,
                        new_ws=websocket,
                        hello_session_id=msg.payload.session_id,
                        close_code=settings.session_singleton_close_code,
                    )
                    session.capabilities = dict(msg.payload.capabilities)
                    session_holder["session"] = session
                    welcome = WelcomeMessage(
                        payload=WelcomePayload(
                            session_id=session.session_id,
                            resumed=resumed,
                            task_board_snapshot=session.task_board_snapshot(),
                        ),
                    )
                    session.supervisor.attach_task_events(
                        make_activity_event_emitter(session)
                    )
                    await send_json(websocket, welcome)
                    continue

                await _handle_text(websocket, raw, session_holder["session"], settings)

            elif "bytes" in message and message["bytes"] is not None:
                session = session_holder["session"]
                if session is None:
                    continue
                await _handle_binary(websocket, message["bytes"], session)


async def _handle_text(
    websocket: WebSocket, raw: str, session: UserSession, settings: Settings
) -> None:
    try:
        msg = parse_client_message(raw)
    except Exception as e:
        log.warning("ws.parse_error", error=str(e), user_id=session.user_id)
        err = ErrorMessage(payload=ErrorPayload(code=4400, message=f"Invalid message: {e}"))
        await send_json(websocket, err)
        return

    if isinstance(msg, ChatMessage):
        await _handle_chat(websocket, msg, session, settings)

    elif isinstance(msg, PingMessage):
        pong = PongMessage(payload=PongPayload(t=msg.payload.t))
        await send_json(websocket, pong)

    elif isinstance(msg, AudioStartMessage):
        session.interrupt.begin_listening()
        session.voice_capture_active = True
        session.voice_chunks = []

    elif isinstance(msg, AudioEndMessage):
        await _handle_audio_end(websocket, msg, session, settings)

    elif isinstance(msg, InterruptMessage):
        await _handle_interrupt(websocket, msg, session)

    elif isinstance(msg, ClientStateMessage):
        prev_playback = session.client_control.playback
        session.client_control.handle_client_state(msg.payload)
        if prev_playback == "playing" and msg.payload.playback == "idle":
            from server.transport.chat_queue import (
                drain_queued_chat,
                try_deliver_pending_chat,
            )

            settings = websocket.app.state.settings
            await try_deliver_pending_chat(websocket, session, settings)
            if (
                session.queued_chat is not None
                or session.pending_chat_delivery is not None
            ):
                engine_pool = websocket.app.state.engine_pool
                from server.transport.turn_coordinator import run_supervisor_text_turn

                async def _run_queued_chat_turn(
                    ws, sess, text, st, pool, *, force_voice: bool = False
                ) -> None:
                    await run_supervisor_text_turn(
                        ws,
                        sess,
                        text,
                        st,
                        pool,
                        input_kind="chat",
                        force_voice=force_voice,
                    )

                await drain_queued_chat(
                    session,
                    websocket,
                    engine_pool,
                    run_chat_turn=_run_queued_chat_turn,
                )

    elif isinstance(msg, ModeMessage):
        from server.orchestrator.meeting import on_mode_change

        engine_pool = websocket.app.state.engine_pool
        await on_mode_change(
            session,
            msg.payload.mode,
            websocket,
            engine_pool,
        )

    elif isinstance(msg, HelloMessage):
        echo = EchoMessage(
            payload=EchoPayload(kind="hello", payload=msg.model_dump().get("payload", {})),
        )
        await send_json(websocket, echo)

    else:
        echo = EchoMessage(
            payload=EchoPayload(kind=msg.type, payload=msg.model_dump().get("payload", {})),
        )
        await send_json(websocket, echo)


async def _handle_interrupt(
    websocket: WebSocket, msg: InterruptMessage, session: UserSession
) -> None:
    from server.orchestrator.directives import strip_directives
    from server.voice.delivery import deliver_interrupted_partial

    partial = strip_directives(session.accumulated_partial)
    await send_interrupt_controls(
        websocket,
        turn_id=session.interrupt.turn_id or None,
        reason=f"interrupt:{msg.payload.source}",
    )
    await session.interrupt.handle_interrupt(msg.payload.source)
    if session.turn_task and not session.turn_task.done():
        session.turn_task.cancel()
    if session.queued_chat_task and not session.queued_chat_task.done():
        session.queued_chat_task.cancel()
        session.queued_chat = None
        session.queued_chat_task = None
    if partial and session.interrupt.turn_id:
        await deliver_interrupted_partial(
            websocket,
            turn_id=session.interrupt.turn_id,
            partial_text=partial,
        )
        await persist_interrupted_assistant(session, partial)
    await send_client_control(
        websocket, "start_capture", "interrupted", turn_id=session.interrupt.turn_id
    )
    session.accumulated_partial = ""


async def _handle_binary(websocket: WebSocket, data: bytes, session: UserSession) -> None:
    if not session.voice_capture_active:
        log.debug("ws.binary_ignored", size=len(data), user_id=session.user_id)
        return
    if session_busy(session):
        return
    session.voice_chunks.append(data)


async def _handle_audio_end(
    websocket: WebSocket,
    msg: AudioEndMessage,
    session: UserSession,
    settings: Settings,
) -> None:
    from server.voice.transcript import voice_pcm_is_viable

    if not session.voice_capture_active:
        return

    pcm_chunks = list(session.voice_chunks)
    session.voice_capture_active = False
    session.voice_chunks = []
    session.interrupt.begin_listening()

    if msg.payload.discard or not voice_pcm_is_viable(pcm_chunks):
        log.debug(
            "audio_end.skipped",
            user_id=session.user_id,
            discard=msg.payload.discard,
            bytes=sum(len(c) for c in pcm_chunks),
        )
        session.pending_voice_chunks = None
        return

    if session.turn_task and not session.turn_task.done():
        defer_voice_utterance(session, pcm_chunks)
        return

    if session.client_control.mode == "meeting":
        await start_meeting_turn(websocket, session, settings, pcm_chunks)
    else:
        await start_voice_turn(websocket, session, settings, pcm_chunks)


async def _handle_chat(
    websocket: WebSocket, msg: ChatMessage, session: UserSession, settings: Settings
) -> None:
    try:
        await _handle_chat_inner(websocket, msg, session, settings)
    except Exception:
        log.exception(
            "ws.chat_failed",
            user_id=session.user_id,
            text=(msg.payload.text or "")[:80],
        )
        err = ErrorMessage(
            payload=ErrorPayload(code=4500, message="Could not process chat message")
        )
        await send_json(websocket, err)


async def _handle_chat_inner(
    websocket: WebSocket, msg: ChatMessage, session: UserSession, settings: Settings
) -> None:
    log.info(
        "ws.chat_received",
        user_id=session.user_id,
        session_id=session.session_id,
        chars=len(msg.payload.text or ""),
    )
    decision = compute_respond_via(
        capabilities_tts=session.capabilities.get("tts", True),
        client_state=session.client_control,
        input_kind="chat",
    )

    should_queue = chat_should_queue(
        session, interrupt_policy=decision.interrupt_policy
    )
    if should_queue:
        from server.orchestrator.tool_fallback import is_trivial_chat_followup
        from server.transport.chat_queue import enqueue_chat

        if is_trivial_chat_followup(msg.payload.text) and (
            session.queued_chat is not None
            or session.pending_chat_delivery is not None
            or (
                session.queued_compute_task is not None
                and not session.queued_compute_task.done()
            )
        ):
            log.debug(
                "ws.chat_ignored_trivial",
                user_id=session.user_id,
                text=msg.payload.text,
            )
            return
        from server.transport.outbound import send_json
        from server.transport.protocol import CaptionMessage, CaptionPayload

        enqueue_chat(session, msg.payload.text, prefer_voice=True)
        await send_json(
            websocket,
            CaptionMessage(
                payload=CaptionPayload(
                    text="Got it — working on that now while I finish speaking.",
                    partial=False,
                    turn_id=None,
                ),
            ),
        )
        engine_pool = websocket.app.state.engine_pool
        from server.transport.chat_queue import start_background_chat_compute

        await start_background_chat_compute(
            websocket, session, settings, engine_pool
        )
        return

    engine_pool = websocket.app.state.engine_pool
    session.turn_task = asyncio.create_task(
        _run_chat_turn(websocket, session, msg.payload.text, settings, engine_pool),
        name=f"chat-turn-{session.user_id}",
    )
    session.interrupt.attach_turn_task(session.turn_task)


async def _run_chat_turn(
    websocket: WebSocket,
    session: UserSession,
    text: str,
    settings: Settings,
    engine_pool: EnginePool,
    *,
    force_voice: bool = False,
) -> None:
    from server.transport.turn_coordinator import run_supervisor_text_turn

    await run_supervisor_text_turn(
        websocket,
        session,
        text,
        settings,
        engine_pool,
        input_kind="chat",
        force_voice=force_voice,
    )


async def _close_auth_failed(websocket: WebSocket, *, code: int, reason: str) -> None:
    if websocket.client_state != WebSocketState.CONNECTED:
        await websocket.accept()
    await websocket.close(code=code, reason=reason)
