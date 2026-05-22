from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.websockets import WebSocket

from server.transport.outbound import send_json
from server.transport.protocol import CaptionMessage, CaptionPayload
from server.voice.interrupt import InterruptController


def make_token_accumulator(
    *,
    accumulate: Callable[[str], None],
) -> Callable[[str], Awaitable[None]]:
    async def on_token(token: str) -> None:
        if token:
            accumulate(token)

    return on_token


def make_streaming_caption_handler(
    *,
    websocket: WebSocket,
    turn_id: str,
    interrupt: InterruptController,
    accumulate: Callable[[str], None],
    emit_partial_captions: bool,
) -> Callable[[str], Awaitable[None]]:
    async def on_token(token: str) -> None:
        if interrupt.tts_cancelled() or not token:
            return
        accumulate(token)
        if not emit_partial_captions:
            return
        await send_json(
            websocket,
            CaptionMessage(
                payload=CaptionPayload(text=token, partial=True, turn_id=turn_id),
            ),
        )

    return on_token
