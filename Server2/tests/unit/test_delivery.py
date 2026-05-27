from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from server.voice.delivery import deliver_turn_output


@pytest.mark.asyncio
async def test_deliver_turn_output_falls_back_when_streaming_pipeline_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = MagicMock()
    interrupt = MagicMock()
    interrupt.tts_cancelled.return_value = False
    tts = MagicMock()

    pipeline = MagicMock()
    pipeline.audio_delivered = False

    begin_tts = AsyncMock(return_value=True)
    monkeypatch.setattr("server.voice.delivery.begin_tts_with_echo_suppression", begin_tts)
    monkeypatch.setattr("server.voice.delivery.send_json", AsyncMock())

    await deliver_turn_output(
        ws,
        turn_id="t1",
        assistant_text="Hello there.",
        respond_via="voice_and_chat",
        interrupt=interrupt,
        tts=tts,
        suppression_delay_ms=0,
        stream_captions_during_llm=True,
        streaming_pipeline=pipeline,
    )

    begin_tts.assert_awaited_once()
