from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.config import reset_settings
from server.memory.meeting_summarizer import (
    MeetingSummaryOutput,
    _parse_meeting_summary_json,
    schedule_post_meeting_summary,
    summarize_meeting,
)
from server.orchestrator.meeting import MeetingState, on_mode_change
from server.orchestrator.supervisor import Supervisor
from server.transport.session_registry import UserSession


def test_parse_meeting_summary_json() -> None:
    raw = '{"summary": "Discussed Q3 goals.", "action_items": ["Send deck"]}'
    parsed = _parse_meeting_summary_json(raw)
    assert parsed is not None
    assert parsed.summary == "Discussed Q3 goals."
    assert parsed.action_items == ["Send deck"]


@pytest.mark.asyncio
async def test_mode_exit_schedules_post_meeting_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[str] = []

    def fake_schedule(**kwargs: object) -> None:
        scheduled.append(str(kwargs.get("meeting_id")))

    monkeypatch.setattr(
        "server.memory.meeting_summarizer.schedule_post_meeting_summary",
        fake_schedule,
    )
    emit = AsyncMock()
    monkeypatch.setattr("server.orchestrator.meeting._emit_meeting_event", emit)
    monkeypatch.setattr(
        "server.orchestrator.meeting.send_client_control",
        AsyncMock(),
    )

    session = UserSession(
        user_id="u1",
        session_id="s1",
        supervisor=Supervisor(user_id="u1", session_id="s1"),
    )
    session.client_control.set_mode("meeting")
    session.meeting_state = MeetingState(meeting_id="20260607-120000", started_at=1.0)

    websocket = MagicMock()
    engine_pool = MagicMock()

    await on_mode_change(session, "conversation", websocket, engine_pool)

    assert session.client_control.mode == "conversation"
    assert session.meeting_state is None
    assert scheduled == ["20260607-120000"]


@pytest.mark.asyncio
async def test_background_summary_persists_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_settings()

    async def fake_summarize(**kwargs: object) -> MeetingSummaryOutput:
        return MeetingSummaryOutput(
            summary="Team aligned on launch date.",
            action_items=["Email stakeholders"],
        )

    monkeypatch.setattr(
        "server.memory.meeting_summarizer.summarize_meeting",
        fake_summarize,
    )
    monkeypatch.setattr(
        "server.memory.meeting_summarizer.list_meeting_chunks",
        lambda _mid, _uid: [MagicMock()],
    )
    set_fact = AsyncMock()
    monkeypatch.setattr("server.memory.meeting_summarizer.facts.set_fact", set_fact)

    schedule_post_meeting_summary(
        meeting_id="m-post",
        user_id="u1",
        started_at=1.0,
        ended_at=2.0,
        engine_pool=MagicMock(),
    )
    await asyncio.sleep(0.05)

    set_fact.assert_called_once()
    key = set_fact.call_args[0][1]
    assert key == "meeting:m-post:summary"
