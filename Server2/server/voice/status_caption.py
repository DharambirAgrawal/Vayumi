from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.websockets import WebSocket

from server.transport.outbound import send_json
from server.transport.protocol import CaptionMessage, CaptionPayload

if False:  # TYPE_CHECKING
    from server.voice.streaming_tts import StreamingTtsPipeline


async def send_status_caption(websocket: WebSocket, *, turn_id: str, text: str) -> None:
    """Live caption while tools run (partial). Pair with TTS via make_status_caption_handler."""
    if not text.strip():
        return
    await send_json(
        websocket,
        CaptionMessage(
            payload=CaptionPayload(text=text.strip(), partial=True, turn_id=turn_id),
        ),
    )


def make_status_caption_handler(
    websocket: WebSocket,
    *,
    turn_id: str,
    pipeline: "StreamingTtsPipeline | None" = None,
) -> Callable[[str], Awaitable[None]]:
    async def on_status_caption(text: str) -> None:
        if not text.strip():
            return
        await send_status_caption(websocket, turn_id=turn_id, text=text)
        if pipeline is not None:
            await pipeline.enqueue_sentence(text)

    return on_status_caption
