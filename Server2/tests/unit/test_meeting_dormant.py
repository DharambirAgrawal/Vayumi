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
    session.meeting_state = MeetingState(meeting_id="m1", started_at=0.0)
    return session


@pytest.mark.asyncio
async def test_passive_transcript_does_not_invoke_supervisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_turn = AsyncMock()
    monkeypatch.setattr(
        "server.transport.turn_coordinator.run_supervisor_text_turn",
        run_turn,
    )
    store_chunk = AsyncMock()
    monkeypatch.setattr(
        "server.orchestrator.meeting.store_meeting_chunk",
        store_chunk,
    )

    session = _session()
    websocket = MagicMock()
    websocket.app.state.settings = MagicMock()

    await handle_meeting_transcript(
        session,
        "The budget is two million",
        websocket,
        MagicMock(),
        "turn-1",
        websocket.app.state.settings,
    )

    run_turn.assert_not_called()
    assert len(session.meeting_state.buffer) == 1
    assert session.meeting_state.buffer[0].text == "The budget is two million"
