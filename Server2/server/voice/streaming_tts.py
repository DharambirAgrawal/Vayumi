from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from starlette.websockets import WebSocket

from server.logger import get_logger
from server.orchestrator.directives import strip_directives, strip_internal_tool_blocks
from server.orchestrator.prose import sanitize_spoken_prose
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
from server.voice.echo_suppression import schedule_start_capture
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
        self._last_emitted: str = ""
        self._queued_sentences = 0

    @property
    def audio_delivered(self) -> bool:
        """True once audio_start was sent and at least one PCM frame was streamed."""
        return self._audio_started

    async def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(
                self._worker(),
                name=f"streaming-tts-{self._turn_id}",
            )

    async def enqueue_sentence(self, sentence: str) -> None:
        """Speak a full sentence immediately (e.g. ack before tools finish)."""
        clean = sanitize_spoken_prose(
            strip_internal_tool_blocks(strip_directives(sentence)).strip()
        )
        if self._is_unspeakable(clean) or self._is_duplicate(clean):
            return
        self._queued_sentences += 1
        await self._queue.put(clean)

    async def feed(self, token: str) -> None:
        if not token or self._interrupt.tts_cancelled():
            return
        self._buffer += token
        sentences, self._buffer = drain_complete_sentences(self._buffer)
        for sentence in sentences:
            clean = sanitize_spoken_prose(
                strip_internal_tool_blocks(strip_directives(sentence)).strip()
            )
            if self._is_unspeakable(clean) or self._is_duplicate(clean):
                continue
            self._queued_sentences += 1
            await self._queue.put(clean)

    async def flush(self) -> None:
        tail = sanitize_spoken_prose(
            strip_internal_tool_blocks(strip_directives(self._buffer)).strip()
        )
        self._buffer = ""
        if self._is_unspeakable(tail) or self._is_duplicate(tail):
            return
        self._queued_sentences += 1
        await self._queue.put(tail)

    async def finish(self, suppression_delay_ms: int) -> bool:
        await self._queue.put(_SENTINEL)
        if self._worker_task is not None:
            await self._worker_task
            self._worker_task = None

        if not self._audio_started:
            if self._queued_sentences:
                log.warning(
                    "streaming_tts.no_audio",
                    turn_id=self._turn_id,
                    queued=self._queued_sentences,
                )
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
            schedule_start_capture(
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
            sentence = sanitize_spoken_prose(str(item))
            if self._is_unspeakable(sentence) or self._is_duplicate(sentence):
                continue
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
                self._mark_spoken(sentence)
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

    def _is_unspeakable(self, sentence: str) -> bool:
        if not sentence or self._interrupt.tts_cancelled():
            return True
        normalized = " ".join(sentence.split()).strip().lower()
        if not normalized:
            return True
        return normalized in {"?", "!", ".", "...", "…"}

    def _normalize_for_dedup(self, sentence: str) -> str:
        normalized = " ".join(sentence.split()).strip().lower()
        return normalized.rstrip(".,!?;:-—…")

    def _is_duplicate(self, sentence: str) -> bool:
        normalized = self._normalize_for_dedup(sentence)
        if not normalized:
            return True
        if not self._last_emitted:
            return False
        if normalized == self._last_emitted:
            return True
        # Same phrase spoken once without terminal punctuation, again with "." 
        return normalized.startswith(self._last_emitted) or self._last_emitted.startswith(
            normalized
        )

    def _mark_spoken(self, sentence: str) -> None:
        self._last_emitted = self._normalize_for_dedup(sentence)

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
