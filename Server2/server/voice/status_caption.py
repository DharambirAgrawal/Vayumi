from __future__ import annotations

from starlette.websockets import WebSocket

from server.transport.outbound import send_json
from server.transport.protocol import CaptionMessage, CaptionPayload


async def send_status_caption(websocket: WebSocket, *, turn_id: str, text: str) -> None:
    """Live caption while tools run — never spoken (partial, stripped before TTS)."""
    if not text.strip():
        return
    await send_json(
        websocket,
        CaptionMessage(
            payload=CaptionPayload(text=text.strip(), partial=True, turn_id=turn_id),
        ),
    )
