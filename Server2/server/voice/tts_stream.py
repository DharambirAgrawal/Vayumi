from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.websockets import WebSocket

from server.transport.outbound import send_audio_frame
from server.voice.interrupt import InterruptController
from server.voice.sentence_buffer import SENTENCE_BOUNDARY_RE
from server.voice.tts.kokoro import KokoroTTS


async def stream_tts_sentences(
    *,
    websocket: WebSocket,
    tts: KokoroTTS,
    text: str,
    interrupt: InterruptController,
    on_sentence_caption: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    sentences = SENTENCE_BOUNDARY_RE.split(text)
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if interrupt.tts_cancelled():
            break
        if on_sentence_caption is not None:
            await on_sentence_caption(sentence)
        async for frame in tts.synthesize_stream(sentence):
            if interrupt.tts_cancelled():
                break
            await send_audio_frame(websocket, frame.pcm)
