from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.config import reset_settings
from server.orchestrator.meeting import (
    MeetingState,
    MeetingUtterance,
    append_utterance,
    maybe_flush_chunk,
)
from server.orchestrator.supervisor import Supervisor
from server.transport.session_registry import UserSession


def _session() -> UserSession:
    session = UserSession(
        user_id="u1",
        session_id="s1",
        supervisor=Supervisor(user_id="u1", session_id="s1"),
    )
    session.meeting_state = MeetingState(
        meeting_id="m1",
        started_at=time.time(),
        last_chunk_flush_at=time.time() - 60,
    )
    return session


@pytest.mark.asyncio
async def test_flush_writes_lancedb_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_settings()
    monkeypatch.setenv("MEETING_CHUNK_INTERVAL_SECONDS", "0")
    reset_settings()

    stored: list[dict[str, object]] = []

    async def fake_store(**kwargs: object) -> None:
        stored.append(kwargs)

    monkeypatch.setattr(
        "server.orchestrator.meeting.store_meeting_chunk",
        fake_store,
    )

    session = _session()
    websocket = MagicMock()

    await append_utterance(
        session,
        text="First point on the roadmap",
        websocket=websocket,
        turn_id="t1",
    )

    assert len(stored) == 1
    assert stored[0]["meeting_id"] == "m1"
    assert stored[0]["user_id"] == "u1"
    assert "SPEAKER_00" in str(stored[0]["text"])
    assert session.meeting_state.buffer == []


@pytest.mark.asyncio
async def test_speaker_rotates_on_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_settings()
    monkeypatch.setenv("MEETING_SPEAKER_GAP_SECONDS", "1")
    reset_settings()

    store = AsyncMock()
    monkeypatch.setattr("server.orchestrator.meeting.store_meeting_chunk", store)

    session = _session()
    session.meeting_state.last_utterance_at = time.time() - 5
    websocket = MagicMock()

    await append_utterance(
        session,
        text="After a long pause",
        websocket=websocket,
        turn_id="t2",
    )

    assert session.meeting_state.current_speaker == "SPEAKER_01"


@pytest.mark.asyncio
async def test_maybe_flush_respects_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_settings()
    monkeypatch.setenv("MEETING_CHUNK_INTERVAL_SECONDS", "999")
    reset_settings()

    store = AsyncMock()
    monkeypatch.setattr("server.orchestrator.meeting.store_meeting_chunk", store)

    session = _session()
    session.meeting_state.buffer.append(
        MeetingUtterance("SPEAKER_00", "pending", time.time())
    )

    await maybe_flush_chunk(session)
    store.assert_not_called()
