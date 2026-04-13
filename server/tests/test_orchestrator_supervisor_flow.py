from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from orchestrator import supervisor


class _FakeMainWorker:
    def __init__(self, stream_events):
        self._stream_events = stream_events
        self.last_update = None

    def request(self, payload, timeout=10):
        self.last_update = payload
        return {"ok": True}

    def stream(self, payload, timeout_s=20):
        for ev in self._stream_events:
            yield ev


class _FakeWorkerStore:
    def __init__(self, stream_events):
        self._main = _FakeMainWorker(stream_events)

    def ensure(self, session_id, model_hint, messages):
        return self._main


@pytest.mark.asyncio
async def test_handle_turn_emits_chatbot_response_and_end(monkeypatch):
    stream = [
        {"ok": True, "event": "chunk", "text": "Hello from orchestrator."},
        {"ok": True, "event": "done"},
    ]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    events = []
    async for event in supervisor.handle_turn(
        transcript="hi",
        session_id="session-a",
        context={"speaker_id": "speaker-a", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        events.append(event)

    kinds = [e["event"] for e in events]
    assert "agent_thinking" in kinds
    assert "chatbot_response" in kinds
    assert "agent_response_end" in kinds
    assert any(e.get("text") == "Hello from orchestrator." for e in events if e["event"] == "chatbot_response")


@pytest.mark.asyncio
async def test_handle_turn_delegates_and_switches_mode(monkeypatch):
    stream = [
        {
            "ok": True,
            "event": "chunk",
            "text": "Starting now.\n[DELEGATE]\ntask: Find docs\ncapability: research\n\n[MODE_SWITCH]\nmode: meeting",
        },
        {"ok": True, "event": "done"},
    ]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))

    spawned = []

    def _fake_spawn(speaker_id, directive, model_hint):
        spawned.append((speaker_id, directive, model_hint))

    monkeypatch.setattr(supervisor, "_spawn_sub_agent", _fake_spawn)

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    events = []
    async for event in supervisor.handle_turn(
        transcript="please do it",
        session_id="session-b",
        context={"speaker_id": "speaker-b", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        events.append(event)

    assert spawned
    assert supervisor.session_mode_store.get("session-b") == "meeting"
    chatbot = [e for e in events if e["event"] == "chatbot_response"]
    assert chatbot and "Starting now." in chatbot[0]["text"]


@pytest.mark.asyncio
async def test_handle_turn_respects_interrupt(monkeypatch):
    stream = [
        {"ok": True, "event": "chunk", "text": "This should be dropped"},
        {"ok": True, "event": "done"},
    ]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    await supervisor.handle_interrupt("session-c")

    events = []
    async for event in supervisor.handle_turn(
        transcript="hi",
        session_id="session-c",
        context={"speaker_id": "speaker-c", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        events.append(event)

    assert not any(e["event"] == "chatbot_response" for e in events)
    assert supervisor.interrupt_store.is_interrupted("session-c") is False
