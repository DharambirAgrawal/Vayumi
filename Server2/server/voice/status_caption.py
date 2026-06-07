from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from starlette.websockets import WebSocket

from server.transport.outbound import send_json
from server.transport.protocol import CaptionMessage, CaptionPayload

if TYPE_CHECKING:
    from server.voice.streaming_tts import StreamingTtsPipeline


async def send_status_caption(websocket: WebSocket, *, turn_id: str, text: str) -> None:
    """Live caption while tools run (partial). Pair with TTS via make_status_caption_handler."""
    from server.orchestrator.prose import sanitize_spoken_prose
    from server.orchestrator.directives import strip_directives, strip_internal_tool_blocks
    
    clean = sanitize_spoken_prose(strip_internal_tool_blocks(strip_directives(text)))
    if not clean.strip():
        return
    await send_json(
        websocket,
        CaptionMessage(
            payload=CaptionPayload(text=clean.strip(), partial=True, turn_id=turn_id),
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
        if pipeline is not None:
            await pipeline.enqueue_sentence(text)
        else:
            await send_status_caption(websocket, turn_id=turn_id, text=text)

    return on_status_caption
