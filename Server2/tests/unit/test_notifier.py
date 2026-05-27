from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from server.config import Settings
from server.orchestrator.notifier import (
    maybe_surface_signal,
    pick_next_signal,
    resolve_proactive_respond_via,
    signal_surface_key,
    user_is_idle,
)
from server.orchestrator.signal_bus import SignalBus
from server.orchestrator.supervisor import Supervisor
from server.orchestrator.task_board import TaskBoard
from server.subagents.report import ReportSignal
from server.transport.client_control import ClientControlSession
from server.transport.session_registry import UserSession
from server.voice.respond_via import compute_respond_via


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql://u:p@localhost/db",
        "redis_url": "redis://localhost:6379/0",
        "notifier_min_interval_seconds": 45.0,
        "notifier_importance_threshold": 0.5,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _session(**client_kwargs: object) -> UserSession:
    supervisor = Supervisor(user_id="u1", session_id="s1")
    cc = ClientControlSession(**client_kwargs)  # type: ignore[arg-type]
    return UserSession(
        user_id="u1",
        session_id="s1",
        supervisor=supervisor,
        client_control=cc,
        capabilities={"tts": True},
    )


def _done_signal(task_id: str = "t1", *, importance: float = 0.5) -> ReportSignal:
    return ReportSignal(
        task_id=task_id,
        kind="DONE",
        summary="Research finished",
        importance=importance,
        created_at=datetime.now(timezone.utc),
    )


def _needs_info_signal(task_id: str = "t2") -> ReportSignal:
    return ReportSignal(
        task_id=task_id,
        kind="NEEDS_INFO",
        summary="Need OAuth scope",
        payload={"question": "Reconnect Gmail?"},
        importance=1.0,
        created_at=datetime.now(timezone.utc),
    )


def test_proactive_done_idle_visible_voice_and_chat() -> None:
    cc = ClientControlSession(visible=True, capture="idle")
    decision = compute_respond_via(
        capabilities_tts=True,
        client_state=cc,
        input_kind="proactive",
    )
    assert decision.respond_via == "voice_and_chat"


def test_proactive_needs_info_visible_voice_and_chat() -> None:
    cc = ClientControlSession(visible=True, capture="idle")
    decision = compute_respond_via(
        capabilities_tts=True,
        client_state=cc,
        input_kind="proactive",
    )
    assert decision.respond_via == "voice_and_chat"


def test_proactive_visible_false_chat_only() -> None:
    cc = ClientControlSession(visible=False, capture="idle")
    decision = compute_respond_via(
        capabilities_tts=True,
        client_state=cc,
        input_kind="proactive",
    )
    assert decision.respond_via == "chat_only"


def test_proactive_done_visible_while_playback_still_voice() -> None:
    session = _session(visible=True, capture="idle", playback="playing")
    decision = resolve_proactive_respond_via(_done_signal(), session)
    assert decision.respond_via == "voice_and_chat"


def test_proactive_done_backgrounded_chat_only() -> None:
    session = _session(visible=False, capture="idle", playback="idle")
    decision = resolve_proactive_respond_via(_done_signal(), session)
    assert decision.respond_via == "chat_only"


def test_proactive_capture_recording_chat_only() -> None:
    cc = ClientControlSession(visible=True, capture="recording")
    decision = compute_respond_via(
        capabilities_tts=True,
        client_state=cc,
        input_kind="proactive",
    )
    assert decision.respond_via == "chat_only"


def test_maybe_surface_done_when_idle() -> None:
    session = _session(visible=True, capture="idle", playback="idle")
    signal = _done_signal()
    assert maybe_surface_signal(signal, session, settings=_settings())


def test_maybe_surface_blocked_when_busy() -> None:
    session = _session(visible=True, capture="idle", playback="idle")
    session.interrupt.begin_thinking("turn-1")
    signal = _done_signal()
    assert not maybe_surface_signal(signal, session, settings=_settings())


def test_maybe_surface_debounce_done_not_needs_info() -> None:
    session = _session(visible=True, capture="idle", playback="idle")
    session.last_proactive_at = time.monotonic()
    done = _done_signal()
    needs = _needs_info_signal()
    assert not maybe_surface_signal(done, session, settings=_settings())
    assert maybe_surface_signal(needs, session, settings=_settings())


def test_maybe_surface_skips_already_surfaced() -> None:
    session = _session(visible=True, capture="idle", playback="idle")
    signal = _done_signal()
    session.surfaced_signal_keys.add(signal_surface_key(signal))
    assert not maybe_surface_signal(signal, session, settings=_settings())


def test_maybe_surface_low_importance_blocked() -> None:
    session = _session(visible=True, capture="idle", playback="idle")
    signal = _done_signal(importance=0.2)
    assert not maybe_surface_signal(signal, session, settings=_settings())


def test_pick_next_signal_prefers_needs_info() -> None:
    done = _done_signal("a")
    needs = _needs_info_signal("b")
    picked = pick_next_signal([done, needs])
    assert picked is not None
    assert picked.kind == "NEEDS_INFO"


def test_user_is_idle_false_when_notifier_inflight() -> None:
    session = _session()
    session.notifier_inflight = True
    assert not user_is_idle(session)


@pytest.mark.asyncio
async def test_signal_bus_notifiable_pending() -> None:
    board = TaskBoard(user_id="u1")
    bus = SignalBus(user_id="u1", task_board=board, persist=False)
    step = ReportSignal(
        task_id="t1",
        kind="STEP",
        summary="working",
        created_at=datetime.now(timezone.utc),
    )
    done = _done_signal()
    await bus.publish(step)
    await bus.publish(done)
    pending = bus.notifiable_pending()
    assert len(pending) == 1
    assert pending[0].kind == "DONE"
