from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from starlette.websockets import WebSocket

from server.logger import get_logger
from server.orchestrator.directives import strip_directives
from server.orchestrator.prose import sanitize_spoken_prose
from server.transport.outbound import send_json
from server.transport.protocol import (
    AssistantChatMessage,
    AssistantChatMessagePayload,
    CaptionMessage,
    CaptionPayload,
    UserMessage,
    UserMessagePayload,
)
from server.voice.echo_suppression import begin_tts_with_echo_suppression
from server.voice.interrupt import InterruptController
from server.voice.respond_via import RespondVia
from server.voice.tts.kokoro import KokoroTTS

if TYPE_CHECKING:
    from server.voice.streaming_tts import StreamingTtsPipeline

log = get_logger("voice.delivery")


async def deliver_user_message(
    websocket: WebSocket,
    *,
    turn_id: str,
    text: str,
    source: Literal["voice", "chat"] = "voice",
) -> None:
    """Show what the user said in the chat thread (voice STT)."""
    stripped = text.strip()
    if not stripped:
        return
    await send_json(
        websocket,
        UserMessage(
            payload=UserMessagePayload(
                text=stripped, turn_id=turn_id, source=source
            ),
        ),
    )


async def deliver_turn_output(
    websocket: WebSocket,
    *,
    turn_id: str,
    assistant_text: str,
    respond_via: RespondVia,
    interrupt: InterruptController,
    tts: KokoroTTS | None,
    suppression_delay_ms: int,
    stream_captions_during_llm: bool = False,
    streaming_pipeline: StreamingTtsPipeline | None = None,
) -> None:
    """§5.5: captions + optional TTS + canonical chat_message."""
    text = sanitize_spoken_prose(strip_directives(assistant_text.strip()))
    streamed_during_llm = streaming_pipeline is not None
    streaming_audio_ok = (
        streaming_pipeline is not None and streaming_pipeline.audio_delivered
    )

    if text and not stream_captions_during_llm:
        await send_json(
            websocket,
            CaptionMessage(
                payload=CaptionPayload(text=text, partial=False, turn_id=turn_id),
            ),
        )

    needs_batch_tts = (
        text
        and respond_via == "voice_and_chat"
        and tts is not None
        and (not streamed_during_llm or not streaming_audio_ok)
    )
    if needs_batch_tts:
        if streamed_during_llm and not streaming_audio_ok:
            log.warning(
                "delivery.tts_fallback",
                turn_id=turn_id,
                chars=len(text),
            )
        tts_caption = None
        if not stream_captions_during_llm:

            async def on_sentence(sentence: str) -> None:
                await send_json(
                    websocket,
                    CaptionMessage(
                        payload=CaptionPayload(
                            text=sentence, partial=False, turn_id=turn_id
                        ),
                    ),
                )

            tts_caption = on_sentence

        await begin_tts_with_echo_suppression(
            websocket,
            turn_id=turn_id,
            interrupt=interrupt,
            tts=tts,
            text=text,
            suppression_delay_ms=suppression_delay_ms,
            on_sentence_caption=tts_caption,
        )

    final = not interrupt.tts_cancelled()
    partial_text = text if text else ""
    await send_json(
        websocket,
        AssistantChatMessage(
            payload=AssistantChatMessagePayload(
                text=partial_text,
                turn_id=turn_id,
                final=final,
            ),
        ),
    )


async def deliver_interrupted_partial(
    websocket: WebSocket,
    *,
    turn_id: str,
    partial_text: str,
) -> None:
    text = sanitize_spoken_prose(strip_directives(partial_text.strip()))
    await send_json(
        websocket,
        AssistantChatMessage(
            payload=AssistantChatMessagePayload(
                text=text,
                turn_id=turn_id,
                final=False,
            ),
        ),
    )
