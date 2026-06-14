from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from server.orchestrator.supervisor import Supervisor
from server.transport.protocol import AudioEndMessage, AudioEndPayload
from server.transport.session_registry import UserSession


def _session(*, mode: str) -> UserSession:
    session = UserSession(
        user_id="u1",
        session_id="s1",
        supervisor=Supervisor(user_id="u1", session_id="s1"),
    )
    session.client_control.set_mode(mode)  # type: ignore[arg-type]
    session.voice_capture_active = True
    session.voice_chunks = [b"\x00" * 9600]
    return session


@pytest.mark.asyncio
async def test_audio_end_routes_to_meeting_turn_in_meeting_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_meeting = AsyncMock()
    start_voice = AsyncMock()
    monkeypatch.setattr(
        "server.transport.ws.start_meeting_turn",
        start_meeting,
    )
    monkeypatch.setattr(
        "server.transport.ws.start_voice_turn",
        start_voice,
    )

    from server.transport.ws import _handle_audio_end

    session = _session(mode="meeting")
    websocket = MagicMock()
    settings = MagicMock()
    msg = AudioEndMessage(payload=AudioEndPayload())

    await _handle_audio_end(websocket, msg, session, settings)

    start_meeting.assert_called_once()
    start_voice.assert_not_called()


@pytest.mark.asyncio
async def test_audio_end_routes_to_voice_turn_in_conversation_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_meeting = AsyncMock()
    start_voice = AsyncMock()
    monkeypatch.setattr(
        "server.transport.ws.start_meeting_turn",
        start_meeting,
    )
    monkeypatch.setattr(
        "server.transport.ws.start_voice_turn",
        start_voice,
    )

    from server.transport.ws import _handle_audio_end

    session = _session(mode="conversation")
    websocket = MagicMock()
    settings = MagicMock()
    msg = AudioEndMessage(payload=AudioEndPayload())

    await _handle_audio_end(websocket, msg, session, settings)

    start_voice.assert_called_once()
    start_meeting.assert_not_called()
