from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from server.auth import AuthError, verify_token
from server.engine.pool import CompletionPriority, CompletionRequest
from server.engine.prompt import MainPromptContext, build_main_prompt
from server.logger import get_logger
from server.transport.protocol import (
    AudioEndMessage,
    AudioStartMessage,
    CaptionMessage,
    CaptionPayload,
    ChatMessage,
    EchoMessage,
    EchoPayload,
    ErrorMessage,
    ErrorPayload,
    InterruptMessage,
    PingMessage,
    PongMessage,
    PongPayload,
    ServerMessage,
    WelcomeMessage,
    WelcomePayload,
    parse_client_message,
    serialize_server_message,
)
from server.voice.interrupt import InterruptController
from server.voice.turn import run_voice_turn

if TYPE_CHECKING:
    from server.config import Settings
    from server.engine.pool import EnginePool
    from server.voice.stt.groq import GroqWhisper
    from server.voice.tts.kokoro import KokoroTTS

log = get_logger("transport.ws")


@dataclass
class _VoiceCapture:
    active: bool = False
    sample_rate: int = 16000
    chunks: list[bytes] = field(default_factory=list)


@dataclass
class _WsSession:
    user_id: str
    interrupt: InterruptController = field(default_factory=InterruptController)
    capture: _VoiceCapture = field(default_factory=_VoiceCapture)
    turn_task: asyncio.Task[None] | None = None


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

    welcome = WelcomeMessage(
        payload=WelcomePayload(session_id=token_payload.session_id),
    )
    await send_json(websocket, welcome)

    session = _WsSession(user_id=token_payload.user_id)

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_inbound_loop(websocket, session))
    except* WebSocketDisconnect:
        log.info("ws.disconnected", user_id=token_payload.user_id)
    except* Exception as eg:
        for exc in eg.exceptions:
            log.error("ws.error", error=str(exc), user_id=token_payload.user_id)
    finally:
        if session.turn_task and not session.turn_task.done():
            session.turn_task.cancel()


async def _inbound_loop(websocket: WebSocket, session: _WsSession) -> None:
    while True:
        message = await websocket.receive()
        msg_type = message.get("type", "")

        if msg_type == "websocket.disconnect":
            raise WebSocketDisconnect()

        if msg_type == "websocket.receive":
            if "text" in message and message["text"] is not None:
                await _handle_text(websocket, message["text"], session)
            elif "bytes" in message and message["bytes"] is not None:
                await _handle_binary(websocket, message["bytes"], session)


async def _handle_text(websocket: WebSocket, raw: str, session: _WsSession) -> None:
    try:
        msg = parse_client_message(raw)
    except Exception as e:
        log.warning("ws.parse_error", error=str(e), user_id=session.user_id)
        err = ErrorMessage(payload=ErrorPayload(code=4400, message=f"Invalid message: {e}"))
        await send_json(websocket, err)
        return

    if isinstance(msg, ChatMessage):
        await _handle_chat(websocket, msg, session)

    elif isinstance(msg, PingMessage):
        pong = PongMessage(payload=PongPayload(t=msg.payload.t))
        await send_json(websocket, pong)

    elif isinstance(msg, AudioStartMessage):
        session.capture = _VoiceCapture(active=True, sample_rate=msg.payload.sample_rate)
        session.interrupt.begin_listening()
        log.debug("ws.audio_capture_started", user_id=session.user_id)

    elif isinstance(msg, AudioEndMessage):
        await _handle_audio_end(websocket, session)

    elif isinstance(msg, InterruptMessage):
        await session.interrupt.handle_interrupt(msg.payload.source)
        if session.turn_task and not session.turn_task.done():
            session.turn_task.cancel()

    else:
        echo = EchoMessage(
            payload=EchoPayload(kind=msg.type, payload=msg.model_dump().get("payload", {})),
        )
        await send_json(websocket, echo)


async def _handle_binary(websocket: WebSocket, data: bytes, session: _WsSession) -> None:
    if session.capture.active:
        session.capture.chunks.append(data)
        log.debug("ws.binary_buffered", size=len(data), user_id=session.user_id)
        return

    log.debug("ws.binary_ignored", size=len(data), user_id=session.user_id)


async def _handle_audio_end(websocket: WebSocket, session: _WsSession) -> None:
    if not session.capture.active:
        return

    pcm_chunks = list(session.capture.chunks)
    session.capture = _VoiceCapture()
    session.interrupt.begin_listening()

    if session.turn_task and not session.turn_task.done():
        session.turn_task.cancel()

    voice = websocket.app.state.voice
    stt: GroqWhisper = voice["stt"]
    tts: KokoroTTS = voice["tts"]
    engine_pool: EnginePool = websocket.app.state.engine_pool

    session.turn_task = asyncio.create_task(
        run_voice_turn(
            websocket=websocket,
            engine_pool=engine_pool,
            stt=stt,
            tts=tts,
            interrupt=session.interrupt,
            pcm_chunks=pcm_chunks,
            user_id=session.user_id,
        ),
        name=f"voice-turn-{session.user_id}",
    )
    session.interrupt.attach_turn_task(session.turn_task)


async def _handle_chat(websocket: WebSocket, msg: ChatMessage, session: _WsSession) -> None:
    engine_pool: EnginePool = websocket.app.state.engine_pool
    prompt = build_main_prompt(MainPromptContext(user_text=msg.payload.text))
    request = CompletionRequest(prompt=prompt)
    handle = await engine_pool.submit(request, CompletionPriority.P0_MAIN, slot_hint=0)

    full_text = ""
    try:
        async for token in handle:
            full_text += token
            await send_json(
                websocket,
                CaptionMessage(payload=CaptionPayload(text=token, partial=True)),
            )
    except Exception as exc:
        log.error("ws.chat_completion_failed", user_id=session.user_id, error=str(exc))
        err = ErrorMessage(payload=ErrorPayload(code=4500, message="Completion failed"))
        await send_json(websocket, err)
        return

    await send_json(
        websocket,
        CaptionMessage(payload=CaptionPayload(text=full_text, partial=False)),
    )


async def send_json(websocket: WebSocket, message: ServerMessage) -> None:
    if websocket.client_state == WebSocketState.CONNECTED:
        await websocket.send_text(serialize_server_message(message))


async def send_audio_frame(websocket: WebSocket, pcm: bytes) -> None:
    if websocket.client_state == WebSocketState.CONNECTED:
        await websocket.send_bytes(pcm)


async def _close_auth_failed(websocket: WebSocket, *, code: int, reason: str) -> None:
    if websocket.client_state != WebSocketState.CONNECTED:
        await websocket.accept()
    await websocket.close(code=code, reason=reason)
