from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from server.orchestrator.meeting import MeetingState, handle_meeting_transcript
from server.orchestrator.supervisor import Supervisor
from server.transport.session_registry import UserSession


def _session() -> UserSession:
    session = UserSession(
        user_id="u1",
        session_id="s1",
        supervisor=Supervisor(user_id="u1", session_id="s1"),
    )
    session.client_control.set_mode("meeting")
    session.meeting_state = MeetingState(meeting_id="m1", started_at=1.0)
    return session


@pytest.mark.asyncio
async def test_end_meeting_command_finalizes_and_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_mode = AsyncMock()
    monkeypatch.setattr("server.orchestrator.meeting.exit_meeting_mode", exit_mode)

    session = _session()
    websocket = MagicMock()
    settings = MagicMock()
    engine_pool = MagicMock()

    await handle_meeting_transcript(
        session,
        "Hey Vayumi, end meeting mode",
        websocket,
        engine_pool,
        "turn-3",
        settings,
    )

    exit_mode.assert_called_once_with(session, websocket, engine_pool)
