from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from starlette.websockets import WebSocket

from server.logger import get_logger
from server.orchestrator.directives import strip_directives, strip_internal_tool_blocks
from server.transport.client_control import send_client_control, send_tts_play_control
from server.transport.outbound import send_audio_frame, send_json
from server.transport.protocol import (
    CaptionMessage,
    CaptionPayload,
    ServerAudioEndMessage,
    ServerAudioEndPayload,
    ServerAudioStartMessage,
    ServerAudioStartPayload,
)
from server.voice.interrupt import InterruptController
from server.voice.sentence_buffer import drain_complete_sentences
from server.voice.tts.kokoro import KokoroTTS

log = get_logger("voice.streaming_tts")

_SENTINEL = object()


class StreamingTtsPipeline:
    """
    PLAN §5.5: speak each LLM sentence as soon as it is complete, while the
    model continues generating later sentences.
    """

    def __init__(
        self,
        *,
        websocket: WebSocket,
        turn_id: str,
        interrupt: InterruptController,
        tts: KokoroTTS,
        emit_sentence_captions: bool = True,
    ) -> None:
        self._websocket = websocket
        self._turn_id = turn_id
        self._interrupt = interrupt
        self._tts = tts
        self._emit_sentence_captions = emit_sentence_captions
        self._buffer = ""
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._audio_started = False
        self._error = False
        self._interrupted = False

    async def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(
                self._worker(),
                name=f"streaming-tts-{self._turn_id}",
            )

    async def feed(self, token: str) -> None:
        if not token or self._interrupt.tts_cancelled():
            return
        self._buffer += token
        sentences, self._buffer = drain_complete_sentences(self._buffer)
        for sentence in sentences:
            clean = strip_internal_tool_blocks(strip_directives(sentence)).strip()
            if clean:
                await self._queue.put(clean)

    async def flush(self) -> None:
        tail = strip_internal_tool_blocks(strip_directives(self._buffer)).strip()
        self._buffer = ""
        if tail and not self._interrupt.tts_cancelled():
            await self._queue.put(tail)

    async def finish(self, suppression_delay_ms: int) -> bool:
        await self._queue.put(_SENTINEL)
        if self._worker_task is not None:
            await self._worker_task
            self._worker_task = None

        if not self._audio_started:
            return True

        if self._error:
            await send_client_control(
                self._websocket, "clear_queue", "tts_error", turn_id=self._turn_id
            )
            await send_json(
                self._websocket,
                ServerAudioEndMessage(
                    payload=ServerAudioEndPayload(
                        turn_id=self._turn_id, error=True
                    ),
                ),
            )
            return False

        if self._interrupt.tts_cancelled() or self._interrupted:
            await send_json(
                self._websocket,
                ServerAudioEndMessage(
                    payload=ServerAudioEndPayload(
                        turn_id=self._turn_id, interrupted=True
                    ),
                ),
            )
            await send_client_control(
                self._websocket, "clear_queue", "interrupted", turn_id=self._turn_id
            )
            await send_client_control(
                self._websocket, "start_capture", "interrupted", turn_id=self._turn_id
            )
            return False

        await send_json(
            self._websocket,
            ServerAudioEndMessage(
                payload=ServerAudioEndPayload(turn_id=self._turn_id),
            ),
        )
        asyncio.create_task(
            _schedule_start_capture(
                self._websocket,
                turn_id=self._turn_id,
                delay_ms=suppression_delay_ms,
            ),
            name=f"echo-clear-{self._turn_id}",
        )
        return True

    async def cancel(self) -> None:
        self._interrupted = True
        await self._queue.put(_SENTINEL)
        if self._worker_task is not None:
            await self._worker_task
            self._worker_task = None

    async def _worker(self) -> None:
        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                return
            sentence = str(item)
            if self._interrupt.tts_cancelled():
                continue
            try:
                if not self._audio_started:
                    await self._begin_audio()
                if self._emit_sentence_captions:
                    await send_json(
                        self._websocket,
                        CaptionMessage(
                            payload=CaptionPayload(
                                text=sentence,
                                partial=False,
                                turn_id=self._turn_id,
                            ),
                        ),
                    )
                await self._synthesize_sentence(sentence)
            except asyncio.CancelledError:
                self._interrupted = True
                raise
            except Exception as exc:
                log.error(
                    "streaming_tts.sentence_failed",
                    turn_id=self._turn_id,
                    error=str(exc),
                )
                self._error = True
                return

    async def _begin_audio(self) -> None:
        await send_client_control(
            self._websocket, "stop_capture", "tts_start", turn_id=self._turn_id
        )
        await send_tts_play_control(self._websocket, turn_id=self._turn_id)
        await send_json(
            self._websocket,
            ServerAudioStartMessage(
                payload=ServerAudioStartPayload(turn_id=self._turn_id),
            ),
        )
        self._interrupt.begin_speaking()
        self._audio_started = True
        log.debug("streaming_tts.audio_started", turn_id=self._turn_id)

    async def _synthesize_sentence(self, sentence: str) -> None:
        async for frame in self._tts.synthesize_stream(sentence):
            if self._interrupt.tts_cancelled():
                break
            await send_audio_frame(self._websocket, frame.pcm)


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


def make_on_token_with_streaming_tts(
    *,
    base_on_token: Callable[[str], Awaitable[None]] | None,
    pipeline: StreamingTtsPipeline | None,
) -> Callable[[str], Awaitable[None]]:
    async def on_token(token: str) -> None:
        if base_on_token is not None:
            await base_on_token(token)
        if pipeline is not None:
            await pipeline.feed(token)

    return on_token
