from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from server.auth import AuthError, verify_token
from server.engine.pool import CompletionPriority, CompletionRequest
from server.engine.prompt import MainPromptContext, build_main_prompt
from server.logger import get_logger
from server.transport.protocol import (
    CaptionMessage,
    CaptionPayload,
    ChatMessage,
    EchoMessage,
    EchoPayload,
    ErrorMessage,
    ErrorPayload,
    PingMessage,
    PongMessage,
    PongPayload,
    WelcomeMessage,
    WelcomePayload,
    parse_client_message,
    serialize_server_message,
)

if TYPE_CHECKING:
    from server.config import Settings
    from server.engine.pool import EnginePool

log = get_logger("transport.ws")


async def ws_endpoint(websocket: WebSocket) -> None:
    settings: Settings = websocket.app.state.settings

    token = websocket.query_params.get("token", "")
    if not token:
        await websocket.close(code=4401, reason="Missing token")
        return

    try:
        token_payload = await verify_token(
            token,
            app_env=settings.app_env,
            jwt_public_key=settings.jwt_public_key,
        )
    except AuthError as e:
        log.warning("ws.auth_failed", error=e.message)
        await websocket.close(code=e.code, reason=e.message)
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

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_inbound_loop(websocket, token_payload.user_id))
    except* WebSocketDisconnect:
        log.info("ws.disconnected", user_id=token_payload.user_id)
    except* Exception as eg:
        for exc in eg.exceptions:
            log.error("ws.error", error=str(exc), user_id=token_payload.user_id)


async def _inbound_loop(websocket: WebSocket, user_id: str) -> None:
    while True:
        message = await websocket.receive()
        msg_type = message.get("type", "")

        if msg_type == "websocket.disconnect":
            raise WebSocketDisconnect()

        if msg_type == "websocket.receive":
            if "text" in message and message["text"] is not None:
                await _handle_text(websocket, message["text"], user_id)
            elif "bytes" in message and message["bytes"] is not None:
                await _handle_binary(websocket, message["bytes"], user_id)


async def _handle_text(websocket: WebSocket, raw: str, user_id: str) -> None:
    try:
        msg = parse_client_message(raw)
    except Exception as e:
        log.warning("ws.parse_error", error=str(e), user_id=user_id)
        err = ErrorMessage(payload=ErrorPayload(code=4400, message=f"Invalid message: {e}"))
        await send_json(websocket, err)
        return

    if isinstance(msg, ChatMessage):
        await _handle_chat(websocket, msg, user_id)

    elif isinstance(msg, PingMessage):
        pong = PongMessage(payload=PongPayload(t=msg.payload.t))
        await send_json(websocket, pong)

    else:
        echo = EchoMessage(
            payload=EchoPayload(kind=msg.type, payload=msg.model_dump().get("payload", {})),
        )
        await send_json(websocket, echo)


async def _handle_binary(websocket: WebSocket, data: bytes, user_id: str) -> None:
    log.debug("ws.binary_received", size=len(data), user_id=user_id)
    await send_audio_frame(websocket, data)


async def _handle_chat(websocket: WebSocket, msg: ChatMessage, user_id: str) -> None:
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
        log.error("ws.chat_completion_failed", user_id=user_id, error=str(exc))
        err = ErrorMessage(payload=ErrorPayload(code=4500, message="Completion failed"))
        await send_json(websocket, err)
        return

    await send_json(
        websocket,
        CaptionMessage(payload=CaptionPayload(text=full_text, partial=False)),
    )


async def send_json(
    websocket: WebSocket,
    message: WelcomeMessage | EchoMessage | CaptionMessage | PongMessage | ErrorMessage,
) -> None:
    if websocket.client_state == WebSocketState.CONNECTED:
        await websocket.send_text(serialize_server_message(message))


async def send_audio_frame(websocket: WebSocket, pcm: bytes) -> None:
    if websocket.client_state == WebSocketState.CONNECTED:
        await websocket.send_bytes(pcm)
