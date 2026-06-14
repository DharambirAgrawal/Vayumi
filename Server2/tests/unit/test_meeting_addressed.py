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
async def test_addressed_transcript_invokes_supervisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_turn = AsyncMock()
    monkeypatch.setattr(
        "server.transport.turn_coordinator.run_supervisor_text_turn",
        run_turn,
    )

    session = _session()
    websocket = MagicMock()
    settings = MagicMock()
    websocket.app.state.settings = settings
    engine_pool = MagicMock()

    await handle_meeting_transcript(
        session,
        "Hey Vayumi, what's the weather?",
        websocket,
        engine_pool,
        "turn-2",
        settings,
    )

    run_turn.assert_called_once()
    args = run_turn.call_args
    assert args[0][2] == "what's the weather?"
    assert args[1]["computed_respond_via"] == "chat_only"
    assert args[1]["input_kind"] == "voice"
