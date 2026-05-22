from __future__ import annotations

from starlette.websockets import WebSocket, WebSocketState

from server.transport.protocol import ServerMessage, serialize_server_message


async def send_json(websocket: WebSocket, message: ServerMessage) -> None:
    if websocket.client_state == WebSocketState.CONNECTED:
        await websocket.send_text(serialize_server_message(message))


async def send_audio_frame(websocket: WebSocket, pcm: bytes) -> None:
    if websocket.client_state == WebSocketState.CONNECTED:
        await websocket.send_bytes(pcm)
