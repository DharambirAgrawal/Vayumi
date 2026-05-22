from __future__ import annotations

from typing import Literal

from starlette.websockets import WebSocket

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
    tts_streamed_during_llm: bool = False,
) -> None:
    """§5.5: captions + optional TTS + canonical chat_message."""
    text = assistant_text.strip()

    if text and not stream_captions_during_llm:
        await send_json(
            websocket,
            CaptionMessage(
                payload=CaptionPayload(text=text, partial=False, turn_id=turn_id),
            ),
        )

    if (
        text
        and respond_via == "voice_and_chat"
        and tts is not None
        and not tts_streamed_during_llm
    ):
        # Captions already streamed during LLM; avoid duplicate sentence captions at TTS.
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
    elif text and respond_via == "voice_and_chat" and tts is None:
        pass

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
    await send_json(
        websocket,
        AssistantChatMessage(
            payload=AssistantChatMessagePayload(
                text=partial_text,
                turn_id=turn_id,
                final=False,
            ),
        ),
    )
