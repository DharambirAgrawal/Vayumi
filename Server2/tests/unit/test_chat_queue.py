from __future__ import annotations

import asyncio

import pytest

from server.transport.chat_queue import enqueue_chat, wait_until_deliverable
from server.transport.queue_types import QueuedChat
from server.transport.session_busy import session_busy
from server.transport.session_registry import UserSession
from server.voice.interrupt import InterruptController
from server.voice.types import SpeechState


def _session() -> UserSession:
    from server.orchestrator.supervisor import Supervisor

    return UserSession(
        user_id="u1",
        session_id="s1",
        supervisor=Supervisor(user_id="u1", session_id="s1"),
    )


def test_enqueue_chat_replaces_pending() -> None:
    session = _session()
    enqueue_chat(session, "first", prefer_voice=True)
    enqueue_chat(session, "second", prefer_voice=False)
    assert session.queued_chat == QueuedChat(text="second", prefer_voice=False)


@pytest.mark.asyncio
async def test_wait_until_deliverable_waits_for_playback() -> None:
    session = _session()
    session.interrupt.state = SpeechState.IDLE
    session.client_control.playback = "playing"

    async def _flip_playback() -> None:
        await asyncio.sleep(0.15)
        session.client_control.playback = "idle"

    asyncio.create_task(_flip_playback())
    ready = await wait_until_deliverable(
        session, want_voice=True, timeout_s=2.0
    )
    assert ready is True
    assert not session_busy(session)


@pytest.mark.asyncio
async def test_deferred_busy_requeues(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.transport import turn_coordinator as tc

    session = _session()
    session.interrupt.state = SpeechState.THINKING

    enqueued: list[str] = []

    def fake_enqueue(sess: UserSession, text: str, *, prefer_voice: bool = True) -> None:
        del sess, prefer_voice
        enqueued.append(text)

    monkeypatch.setattr("server.transport.chat_queue.enqueue_chat", fake_enqueue)

    class _Ws:
        class state:
            voice = {"tts": None}
            settings = None

        app = state()

    await tc.run_supervisor_text_turn(
        _Ws(),  # type: ignore[arg-type]
        session,
        "continue",
        _Ws.app.settings,  # type: ignore[arg-type]
        engine_pool=None,  # type: ignore[arg-type]
        input_kind="chat",
    )

    assert enqueued == ["continue"]
