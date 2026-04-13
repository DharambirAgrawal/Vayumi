from __future__ import annotations

import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest
from starlette.websockets import WebSocketState

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent.runner import AgentRunner
from orchestrator import supervisor
from orchestrator.session_store import TaskSession, session_store
from orchestrator.worker_base import LiteRTWorker
import main as server_main
from agent.tools import session_tools
from models import ClientConnection, ClientType, Session, TranscriptionSegment, DiarizationSegment


class _FakeMainWorker:
    def __init__(self, stream_events):
        self._stream_events = stream_events

    def request(self, payload, timeout=10):
        return {"ok": True}

    def stream(self, payload, timeout_s=20):
        for ev in self._stream_events:
            yield ev


class _FakeWorkerStore:
    def __init__(self, stream_events):
        self._main = _FakeMainWorker(stream_events)

    def ensure(self, session_id, model_hint, messages):
        return self._main


class _FakeSubWorker:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class _FakeWebSocket:
    client_state = WebSocketState.CONNECTED

    def __init__(self):
        self.sent_json = []
        self.sent_bytes = []

    async def send_json(self, data):
        self.sent_json.append(data)

    async def send_bytes(self, data):
        self.sent_bytes.append(data)


class _FakeTask:
    def __init__(self):
        self._done = False
        self.cancelled = False

    def done(self):
        return self._done

    def cancel(self):
        self.cancelled = True
        self._done = True


class _CancelSpy:
    def __init__(self):
        self.calls = []

    async def cancel(self, session_id: str):
        self.calls.append(session_id)


class _ResetSpy:
    def __init__(self):
        self.calls = []

    async def reset_session(self, session_id: str):
        self.calls.append(session_id)


class _TTSCancelSpy:
    def __init__(self):
        self.calls = []

    async def cancel(self, session_id: str):
        self.calls.append(session_id)


@pytest.fixture(autouse=True)
def _reset_state():
    session_store._tasks.clear()
    supervisor.session_mode_store.clear()
    supervisor.interrupt_store._flags.clear()
    for sid in list(supervisor.history_store._turns.keys()):
        supervisor.history_store.clear(sid)

    server_main.active_response_tasks.clear()
    server_main.live_wake_interrupt_buffers.clear()
    server_main.live_wake_interrupt_checked_bytes.clear()

    yield

    session_store._tasks.clear()
    supervisor.session_mode_store.clear()
    supervisor.interrupt_store._flags.clear()
    server_main.active_response_tasks.clear()
    server_main.live_wake_interrupt_buffers.clear()
    server_main.live_wake_interrupt_checked_bytes.clear()


@pytest.mark.asyncio
async def test_end_to_end_time_tool_call_with_real_main_worker(monkeypatch):
    # Keep external memory infra out of this integration test.
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    events = []
    try:
        async for event in supervisor.handle_turn(
            transcript="what time is it",
            session_id="e2e-time-session",
            context={"speaker_id": "spk", "input_mode": "chat", "vayumi_state": {}},
            model_hint="mock-no-litert",  # forces heuristic loop if LiteRT model is unavailable
        ):
            events.append(event)
    finally:
        supervisor.main_worker_store.stop("e2e-time-session")

    assert any(e.get("event") == "tool_status" and e.get("tool") == "current_time" for e in events)
    assert any(e.get("event") == "chatbot_response" and "Done. Here is what I found" in e.get("text", "") for e in events)


@pytest.mark.asyncio
async def test_runner_supervisor_coordinated_flow_with_logs(monkeypatch, caplog):
    task_id = "task_coordinated"
    session_store.add(
        "spk",
        TaskSession(
            task_id=task_id,
            description="Research updates",
            capability="research",
            status="running",
            tool_ids=["web_search"],
            worker=_FakeSubWorker(),
            pending_question=None,
            step_log=[],
            last_step_message="",
            created_at=time.time(),
            step_count=0,
            max_steps=12,
            timeout_at=time.time() + 30,
        ),
    )

    stream = [
        {"ok": True, "event": "tool_status", "phase": "start", "tool": "web_search", "params": {"query": "ai"}},
        {"ok": True, "event": "tool_status", "phase": "done", "tool": "web_search"},
        {"ok": True, "event": "chunk", "text": "All done."},
        {"ok": True, "event": "done"},
    ]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))
    monkeypatch.setattr(
        supervisor.signal_bus,
        "drain",
        lambda speaker_id: [
            {"type": "STEP", "task_id": task_id, "message": "Searching sources"},
            {"type": "DONE", "task_id": task_id, "message": "Completed", "step_log": ["s1", "s2"]},
        ],
    )

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    caplog.set_level(logging.INFO)
    runner = AgentRunner(model="mock")

    out = []
    async for event in runner.run(
        transcript="search latest",
        session_id="coordinated-session",
        context={"speaker_id": "spk", "input_mode": "chat", "vayumi_state": {}},
    ):
        out.append(event)

    event_types = [e.event_type for e in out]
    assert "thinking" in event_types
    assert "tool_call" in event_types
    assert "response_chunk" in event_types
    assert event_types[-1] == "response_end"

    # Verify bridge logging confirms the request path ran through AgentRunner.
    assert any("Agent running for session coordinated-session" in rec.message for rec in caplog.records)
    assert any("Agent run complete for session coordinated-session" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_interrupt_cleans_runtime_buffers_and_emits_ack(monkeypatch):
    websocket = _FakeWebSocket()
    session = Session(session_id="interrupt-session")
    session.is_ai_speaking = True
    session.current_response_id = "resp_1"
    session.current_response_words = ["hello", "there", "friend"]
    session.current_response_word_index = 2
    session.current_response_checkpoint_index = 1

    server_main.live_wake_interrupt_buffers[session.session_id] = bytearray(b"abc")
    server_main.live_wake_interrupt_checked_bytes[session.session_id] = 3

    fake_task = _FakeTask()
    server_main.active_response_tasks[session.session_id] = fake_task

    cancel_spy = _CancelSpy()
    reset_spy = _ResetSpy()
    tts_spy = _TTSCancelSpy()

    monkeypatch.setattr(server_main, "agent_runner", cancel_spy)
    monkeypatch.setattr(server_main, "audio_pipeline", reset_spy)
    monkeypatch.setattr(server_main, "tts_engine", tts_spy)

    async def _fast_wait_for(awaitable, timeout):
        return None

    monkeypatch.setattr(asyncio, "wait_for", _fast_wait_for)

    await server_main._interrupt_active_response(websocket, session, trigger="wake_word")

    assert cancel_spy.calls == ["interrupt-session"]
    assert reset_spy.calls == ["interrupt-session"]
    assert tts_spy.calls == ["interrupt-session"]
    assert fake_task.cancelled is True
    assert session.session_id not in server_main.live_wake_interrupt_buffers
    assert session.session_id not in server_main.live_wake_interrupt_checked_bytes
    assert any(msg.get("type") == "interrupt_ack" for msg in websocket.sent_json)


def test_response_queue_policy_when_ai_is_busy():
    websocket = _FakeWebSocket()
    session = Session(session_id="queue-session")
    existing_task = _FakeTask()
    server_main.active_response_tasks[session.session_id] = existing_task

    server_main._start_agent_response_with_policy(
        websocket,
        session,
        transcript="second request",
        respond_via="chat_only",
        interrupt_policy="queue",
    )

    queued = getattr(session, "_queued_responses", [])
    assert len(queued) == 1
    assert queued[0]["transcript"] == "second request"


@pytest.mark.asyncio
async def test_capability_gap_signal_is_emitted_and_task_removed(monkeypatch):
    task_id = "task_gap"
    worker = _FakeSubWorker()
    session_store.add(
        "spk",
        TaskSession(
            task_id=task_id,
            description="Need unavailable integration",
            capability="communication",
            status="running",
            tool_ids=["email_reader"],
            worker=worker,
            pending_question=None,
            step_log=[],
            last_step_message="",
            created_at=time.time(),
            step_count=0,
            max_steps=12,
            timeout_at=time.time() + 30,
        ),
    )

    stream = [{"ok": True, "event": "chunk", "text": "Noted."}, {"ok": True, "event": "done"}]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))
    monkeypatch.setattr(
        supervisor.signal_bus,
        "drain",
        lambda speaker_id: [{"type": "CAPABILITY_GAP", "task_id": task_id, "message": "Tool missing", "step_log": []}],
    )

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    events = []
    async for event in supervisor.handle_turn(
        transcript="do it",
        session_id="gap-session",
        context={"speaker_id": "spk", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        events.append(event)

    assert any(e.get("event") == "task_error" for e in events)
    assert session_store.get("spk", task_id) is None
    assert worker.stopped is True


@pytest.mark.asyncio
async def test_chatbot_attachment_tool_returns_session_payload(monkeypatch):
    session = Session(session_id="attachment-session")
    session.attachments.extend(
        [
            {"type": "link", "url": "https://example.com/article"},
            {"type": "image", "url": "https://example.com/image.png", "mime_type": "image/png"},
        ]
    )

    class _AttachmentSessionManager:
        async def get_session(self, session_id: str):
            return session if session_id == session.session_id else None

    monkeypatch.setattr(server_main, "session_manager", _AttachmentSessionManager())

    attachments = await session_tools.get_chatbot_attachments(session.session_id)

    assert attachments == session.attachments


@pytest.mark.asyncio
async def test_session_tools_expose_connected_client_notes_and_transcripts(monkeypatch):
    session = Session(session_id="session-tools")
    session.active_voice_source = ClientType.WEB
    session.web_client = ClientConnection(
        client_type=ClientType.WEB,
        session_id=session.session_id,
        connected_at=datetime.utcnow(),
    )
    session.transcriptions.extend(
        [
            TranscriptionSegment(text="hello there", start_ms=0, end_ms=500, confidence=0.9, final=True),
            TranscriptionSegment(text="second turn", start_ms=500, end_ms=1000, confidence=0.8, final=True),
        ]
    )
    session.meeting_segments.extend(
        [
            DiarizationSegment(speaker="alice", text="Intro", start_ms=0, end_ms=500),
            DiarizationSegment(speaker="bob", text="Follow up", start_ms=500, end_ms=1000),
        ]
    )

    class _ToolSessionManager:
        async def get_session(self, session_id: str):
            return session if session_id == session.session_id else None

    monkeypatch.setattr(server_main, "session_manager", _ToolSessionManager())

    transcript = await session_tools.get_session_transcript(session.session_id)
    summary = await session_tools.get_meeting_summary(session.session_id)
    client_type = await session_tools.get_active_client_type(session.session_id)
    saved = await session_tools.save_session_note(session.session_id, "remember this")

    assert transcript == "hello there\nsecond turn"
    assert "alice: Intro" in summary
    assert "bob: Follow up" in summary
    assert client_type == "web"
    assert saved is True
    assert session.context_notes == ["remember this"]
