from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from starlette.websockets import WebSocket

from server.logger import get_logger
from server.transport.client_control import send_client_control, send_tts_play_control
from server.transport.outbound import send_json
from server.transport.protocol import (
    ServerAudioEndMessage,
    ServerAudioEndPayload,
    ServerAudioStartMessage,
    ServerAudioStartPayload,
)
from server.voice.interrupt import InterruptController
from server.voice.tts.kokoro import KokoroTTS
from server.voice.tts_stream import stream_tts_sentences

log = get_logger("voice.echo_suppression")


async def begin_tts_with_echo_suppression(
    websocket: WebSocket,
    *,
    turn_id: str,
    interrupt: InterruptController,
    tts: KokoroTTS,
    text: str,
    suppression_delay_ms: int,
    on_sentence_caption: Callable[[str], Awaitable[None]] | None = None,
) -> bool:
    """
    Rule 12: only path to audio_start. Sends stop_capture, streams TTS, audio_end.
    Schedules start_capture after suppression_delay_ms unless interrupted.
    Returns True if TTS completed without interrupt.
    """
    await send_client_control(websocket, "stop_capture", "tts_start", turn_id=turn_id)
    await send_tts_play_control(websocket, turn_id=turn_id)
    await send_json(
        websocket,
        ServerAudioStartMessage(payload=ServerAudioStartPayload(turn_id=turn_id)),
    )
    interrupt.begin_speaking()

    interrupted = False
    try:
        await stream_tts_sentences(
            websocket=websocket,
            tts=tts,
            text=text,
            interrupt=interrupt,
            on_sentence_caption=on_sentence_caption,
        )
        if interrupt.tts_cancelled():
            interrupted = True
            await send_json(
                websocket,
                ServerAudioEndMessage(
                    payload=ServerAudioEndPayload(turn_id=turn_id, interrupted=True),
                ),
            )
        else:
            await send_json(
                websocket,
                ServerAudioEndMessage(payload=ServerAudioEndPayload(turn_id=turn_id)),
            )
    except asyncio.CancelledError:
        interrupted = True
        raise
    except Exception as exc:
        log.error("echo_suppression.tts_failed", turn_id=turn_id, error=str(exc))
        await send_client_control(websocket, "clear_queue", "tts_error", turn_id=turn_id)
        await send_json(
            websocket,
            ServerAudioEndMessage(
                payload=ServerAudioEndPayload(turn_id=turn_id, error=True),
            ),
        )
        return False
    finally:
        if interrupted:
            await send_client_control(
                websocket, "clear_queue", "interrupted", turn_id=turn_id
            )
            await send_client_control(
                websocket, "start_capture", "interrupted", turn_id=turn_id
            )
        else:
            asyncio.create_task(
                _schedule_start_capture(
                    websocket,
                    turn_id=turn_id,
                    delay_ms=suppression_delay_ms,
                ),
                name=f"echo-clear-{turn_id}",
            )

    return not interrupted


async def _schedule_start_capture(
    websocket: WebSocket,
    *,
    turn_id: str,
    delay_ms: int,
) -> None:
    await asyncio.sleep(delay_ms / 1000.0)
    from starlette.websockets import WebSocketState

    if websocket.client_state != WebSocketState.CONNECTED:
        return
    await send_client_control(websocket, "start_capture", "echo_clear", turn_id=turn_id)
