from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from server.voice.streaming_tts import StreamingTtsPipeline


@pytest.mark.asyncio
async def test_pipeline_queues_sentences_and_starts_audio() -> None:
    ws = MagicMock()
    ws.client_state = 1
    interrupt = MagicMock()
    interrupt.tts_cancelled.return_value = False

    tts = MagicMock()

    async def fake_synth(text: str, voice: str | None = None):
        yield MagicMock(pcm=b"\x00\x01", sample_rate=16000)

    tts.synthesize_stream = fake_synth

    sent_json: list = []
    sent_audio: list = []

    async def capture_json(websocket, message):
        sent_json.append(message)

    async def capture_audio(websocket, pcm):
        sent_audio.append(pcm)

    import server.voice.streaming_tts as mod

    mod.send_json = capture_json
    mod.send_audio_frame = capture_audio
    mod.send_client_control = AsyncMock()
    mod.send_tts_play_control = AsyncMock()

    pipeline = StreamingTtsPipeline(
        websocket=ws,
        turn_id="t1",
        interrupt=interrupt,
        tts=tts,
    )
    await pipeline.start()
    await pipeline.feed("Hello world. ")
    await pipeline.feed("Second line.")
    await pipeline.flush()
    ok = await pipeline.finish(0)

    assert ok is True
    assert any(getattr(m, "type", None) == "audio_start" for m in sent_json)
    assert len(sent_audio) >= 1
