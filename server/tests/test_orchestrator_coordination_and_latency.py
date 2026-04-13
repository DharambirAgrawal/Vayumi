from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from orchestrator import supervisor
from orchestrator.history_store import history_store
from orchestrator.session_store import TaskSession, session_store


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


class _FakeLiteRTWorker:
    instances = []

    def __init__(self, worker_fn, worker_args):
        self.worker_fn = worker_fn
        self.worker_args = worker_args
        self.requests = []
        self.started = False
        self.stopped = False
        _FakeLiteRTWorker.instances.append(self)

    def start(self):
        self.started = True

    def request(self, payload, timeout=30.0):
        self.requests.append(payload)
        return {"ok": True}

    def stop(self):
        self.stopped = True


@pytest.fixture(autouse=True)
def _reset_orchestrator_state():
    # Keep tests isolated from each other.
    session_store._tasks.clear()
    supervisor.session_mode_store.clear()
    supervisor.interrupt_store._flags.clear()
    for sid in list(history_store._turns.keys()):
        history_store.clear(sid)
    yield
    session_store._tasks.clear()
    supervisor.session_mode_store.clear()
    supervisor.interrupt_store._flags.clear()


@pytest.mark.asyncio
async def test_handle_turn_sets_routing_metadata_chat_vs_voice(monkeypatch):
    stream = [{"ok": True, "event": "chunk", "text": "ok"}, {"ok": True, "event": "done"}]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    chat_events = []
    async for event in supervisor.handle_turn(
        transcript="hello",
        session_id="chat-session",
        context={"speaker_id": "spk", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        chat_events.append(event)

    voice_events = []
    async for event in supervisor.handle_turn(
        transcript="hello",
        session_id="voice-session",
        context={"speaker_id": "spk", "input_mode": "voice", "vayumi_state": {}},
        model_hint="mock",
    ):
        voice_events.append(event)

    chat_response = next(e for e in chat_events if e.get("event") == "chatbot_response")
    voice_response = next(e for e in voice_events if e.get("event") == "chatbot_response")

    assert chat_response["respond_via"] == "chat_only"
    assert chat_response["interrupt_policy"] == "queue"
    assert voice_response["respond_via"] == "voice_and_chat"
    assert voice_response["interrupt_policy"] == "replace"


@pytest.mark.asyncio
async def test_signal_bus_task_events_and_tool_status_passthrough(monkeypatch):
    task_id = "task_abc"
    session_store.add(
        "spk",
        TaskSession(
            task_id=task_id,
            description="Find details",
            capability="research",
            status="running",
            tool_ids=["web_search"],
            worker=_FakeLiteRTWorker(worker_fn=None, worker_args=()),
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
        {"ok": True, "event": "chunk", "text": "Done."},
        {"ok": True, "event": "done"},
    ]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))
    monkeypatch.setattr(
        supervisor.signal_bus,
        "drain",
        lambda speaker_id: [
            {"type": "STEP", "task_id": task_id, "message": "Searching"},
            {"type": "DONE", "task_id": task_id, "message": "Completed", "step_log": ["a", "b"]},
        ],
    )

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    events = []
    async for event in supervisor.handle_turn(
        transcript="go",
        session_id="sig-session",
        context={"speaker_id": "spk", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        events.append(event)

    kinds = [e.get("event") for e in events]
    assert "task_progress" in kinds
    assert "task_complete" in kinds
    assert any(e.get("event") == "tool_status" and e.get("phase") == "start" and e.get("display") for e in events)
    assert any(e.get("event") == "tool_status" and e.get("phase") == "done" for e in events)


@pytest.mark.asyncio
async def test_handle_turn_calls_memory_flush_hook(monkeypatch):
    stream = [{"ok": True, "event": "chunk", "text": "saved"}, {"ok": True, "event": "done"}]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))

    called = []

    def _track_flush(speaker_id: str, transcript: str):
        called.append((speaker_id, transcript))

    monkeypatch.setattr(supervisor, "_safe_add_turn_and_flush", _track_flush)

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    async for _ in supervisor.handle_turn(
        transcript="remember this fact",
        session_id="mem-session",
        context={"speaker_id": "speaker-1", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        pass

    assert called == [("speaker-1", "remember this fact")]


def test_spawn_sub_agent_full_tool_access_uses_all_tools(monkeypatch):
    _FakeLiteRTWorker.instances.clear()
    monkeypatch.setattr(supervisor, "LiteRTWorker", _FakeLiteRTWorker)
    monkeypatch.setattr(supervisor, "load_skill_docs", lambda tool_ids: "")
    monkeypatch.setattr(supervisor, "get_all_tool_ids", lambda: ["web_search", "email_reader", "current_time"])
    monkeypatch.setattr(supervisor, "SUBAGENT_FULL_TOOL_ACCESS", True)

    supervisor._spawn_sub_agent(
        speaker_id="spk",
        directive={"task": "find invoices", "capability": "communication"},
        model_hint="mock",
    )

    assert _FakeLiteRTWorker.instances
    worker = _FakeLiteRTWorker.instances[0]
    assert worker.started is True
    assert worker.requests and worker.requests[0]["cmd"] == "run"

    tasks = session_store._tasks.get("spk", {})
    assert len(tasks) == 1
    task = next(iter(tasks.values()))
    assert set(task.tool_ids) == {"web_search", "email_reader", "current_time"}


@pytest.mark.asyncio
async def test_handle_turn_fast_path_latency(monkeypatch):
    stream = [{"ok": True, "event": "chunk", "text": "quick"}, {"ok": True, "event": "done"}]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    t0 = time.perf_counter()
    events = []
    async for event in supervisor.handle_turn(
        transcript="ping",
        session_id="lat-session",
        context={"speaker_id": "spk", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        events.append(event)
    elapsed = time.perf_counter() - t0

    assert any(e.get("event") == "chatbot_response" for e in events)
    # Soft latency guard for fast mocked path (detect obvious regressions).
    assert elapsed < 1.5


@pytest.mark.asyncio
async def test_handle_turn_waiting_signal_and_answer_to_resume(monkeypatch):
    task_id = "task_need"
    worker = _FakeLiteRTWorker(worker_fn=None, worker_args=())
    session_store.add(
        "spk",
        TaskSession(
            task_id=task_id,
            description="Prepare report",
            capability="productivity",
            status="running",
            tool_ids=["doc_generator"],
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

    stream = [
        {
            "ok": True,
            "event": "chunk",
            "text": "Got your answer.\n[ANSWER_TO]\ntask_id: task_need\nanswer: use quarterly numbers",
        },
        {"ok": True, "event": "done"},
    ]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))
    monkeypatch.setattr(
        supervisor.signal_bus,
        "drain",
        lambda speaker_id: [{"type": "NEEDS_INFO", "task_id": task_id, "message": "Which quarter?"}],
    )

    resumed: list[tuple[str, str, str]] = []

    def _fake_resume(speaker_id: str, resume_task_id: str, answer: str) -> None:
        resumed.append((speaker_id, resume_task_id, answer))

    monkeypatch.setattr(supervisor, "_resume_sub_agent", _fake_resume)

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    events = []
    async for event in supervisor.handle_turn(
        transcript="Use Q4",
        session_id="need-info-session",
        context={"speaker_id": "spk", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        events.append(event)

    assert any(e.get("event") == "task_waiting" for e in events)
    assert resumed == [("spk", "task_need", "use quarterly numbers")]


@pytest.mark.asyncio
async def test_handle_turn_expires_timeout_and_stops_task(monkeypatch):
    task_id = "task_timeout"
    worker = _FakeLiteRTWorker(worker_fn=None, worker_args=())
    session_store.add(
        "spk",
        TaskSession(
            task_id=task_id,
            description="Long operation",
            capability="research",
            status="running",
            tool_ids=["web_search"],
            worker=worker,
            pending_question=None,
            step_log=[],
            last_step_message="",
            created_at=time.time(),
            step_count=0,
            max_steps=12,
            timeout_at=time.time() - 1,
        ),
    )

    stream = [{"ok": True, "event": "chunk", "text": "continuing"}, {"ok": True, "event": "done"}]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    async for _ in supervisor.handle_turn(
        transcript="status?",
        session_id="timeout-session",
        context={"speaker_id": "spk", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        pass

    assert session_store.get("spk", task_id) is None
    assert worker.stopped is True


@pytest.mark.asyncio
async def test_handle_turn_processes_multi_task_signals(monkeypatch):
    running_task = "task_run"
    done_task = "task_done"

    session_store.add(
        "spk",
        TaskSession(
            task_id=running_task,
            description="Find docs",
            capability="research",
            status="running",
            tool_ids=["web_search"],
            worker=_FakeLiteRTWorker(worker_fn=None, worker_args=()),
            pending_question=None,
            step_log=[],
            last_step_message="",
            created_at=time.time(),
            step_count=0,
            max_steps=12,
            timeout_at=time.time() + 30,
        ),
    )
    done_worker = _FakeLiteRTWorker(worker_fn=None, worker_args=())
    session_store.add(
        "spk",
        TaskSession(
            task_id=done_task,
            description="Summarize notes",
            capability="productivity",
            status="running",
            tool_ids=["doc_generator"],
            worker=done_worker,
            pending_question=None,
            step_log=[],
            last_step_message="",
            created_at=time.time(),
            step_count=0,
            max_steps=12,
            timeout_at=time.time() + 30,
        ),
    )

    monkeypatch.setattr(
        supervisor.signal_bus,
        "drain",
        lambda speaker_id: [
            {"type": "STEP", "task_id": running_task, "message": "Searching sources"},
            {"type": "DONE", "task_id": done_task, "message": "Summary ready", "step_log": ["x"]},
        ],
    )
    stream = [{"ok": True, "event": "chunk", "text": "Updated."}, {"ok": True, "event": "done"}]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    events = []
    async for event in supervisor.handle_turn(
        transcript="update me",
        session_id="multi-task-session",
        context={"speaker_id": "spk", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        events.append(event)

    assert any(e.get("event") == "task_progress" for e in events)
    assert any(e.get("event") == "task_complete" for e in events)
    assert session_store.get("spk", running_task) is not None
    assert session_store.get("spk", done_task) is None
    assert done_worker.stopped is True


@pytest.mark.asyncio
async def test_handle_turn_processes_multiple_directives_in_single_reply(monkeypatch):
    stream = [
        {
            "ok": True,
            "event": "chunk",
            "text": (
                "Working on it.\n"
                "[DELEGATE]\n"
                "task: Research open items\n"
                "capability: research\n\n"
                "[STOP]\n"
                "task_id: task_old\n\n"
                "[ANSWER_TO]\n"
                "task_id: task_waiting\n"
                "answer: Use the sales dashboard\n\n"
                "[MODE_SWITCH]\n"
                "mode: meeting\n"
            ),
        },
        {"ok": True, "event": "done"},
    ]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))

    calls: list[tuple[str, str, str]] = []

    def _fake_spawn(speaker_id: str, directive: dict, model_hint: str) -> None:
        calls.append(("spawn", speaker_id, directive["task"]))

    def _fake_stop(speaker_id: str, task_id: str) -> None:
        calls.append(("stop", speaker_id, task_id))

    def _fake_resume(speaker_id: str, task_id: str, answer: str) -> None:
        calls.append(("resume", task_id, answer))

    async def _fake_mode_switch(session_id: str, speaker_id: str, mode: str) -> None:
        calls.append(("mode", session_id, mode))

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "_spawn_sub_agent", _fake_spawn)
    monkeypatch.setattr(supervisor, "_stop_sub_agent", _fake_stop)
    monkeypatch.setattr(supervisor, "_resume_sub_agent", _fake_resume)
    monkeypatch.setattr(supervisor, "_apply_mode_switch", _fake_mode_switch)
    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    events = []
    async for event in supervisor.handle_turn(
        transcript="handle a lot",
        session_id="directive-session",
        context={"speaker_id": "spk", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        events.append(event)

    assert any(e.get("event") == "chatbot_response" and e.get("text") == "Working on it." for e in events)
    assert calls == [
        ("spawn", "spk", "Research open items"),
        ("stop", "spk", "task_old"),
        ("resume", "task_waiting", "Use the sales dashboard"),
        ("mode", "directive-session", "meeting"),
    ]


@pytest.mark.asyncio
async def test_handle_turn_clears_interrupt_without_emitting_response(monkeypatch):
    class _InterruptingWorker:
        def request(self, payload, timeout=10):
            return {"ok": True}

        def stream(self, payload, timeout_s=20):
            yield {"ok": True, "event": "chunk", "text": "partial"}
            supervisor.interrupt_store.set_interrupted("interrupt-session", True)
            yield {"ok": True, "event": "chunk", "text": "ignored"}

    class _InterruptingStore:
        def ensure(self, session_id, model_hint, messages):
            return _InterruptingWorker()

    monkeypatch.setattr(supervisor, "main_worker_store", _InterruptingStore())
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    events = []
    async for event in supervisor.handle_turn(
        transcript="interrupt me",
        session_id="interrupt-session",
        context={"speaker_id": "spk", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        events.append(event)

    assert events == [{"event": "agent_thinking"}]
    assert supervisor.interrupt_store.is_interrupted("interrupt-session") is False


@pytest.mark.asyncio
async def test_handle_turn_keeps_histories_isolated_across_sessions(monkeypatch):
    stream = [{"ok": True, "event": "chunk", "text": "reply"}, {"ok": True, "event": "done"}]
    monkeypatch.setattr(supervisor, "main_worker_store", _FakeWorkerStore(stream))
    monkeypatch.setattr(supervisor, "_safe_get_memory_context", lambda transcript, speaker_id: ("", ""))

    async def _no_task(*args, **kwargs):
        return None

    monkeypatch.setattr(supervisor, "run_on_task", _no_task)
    monkeypatch.setattr(supervisor, "run_on_turns", _no_task)

    async for _ in supervisor.handle_turn(
        transcript="first session message",
        session_id="session-a",
        context={"speaker_id": "speaker-a", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        pass

    async for _ in supervisor.handle_turn(
        transcript="second session message",
        session_id="session-b",
        context={"speaker_id": "speaker-b", "input_mode": "chat", "vayumi_state": {}},
        model_hint="mock",
    ):
        pass

    history_a = history_store.get("session-a")
    history_b = history_store.get("session-b")

    assert len(history_a) == 2
    assert len(history_b) == 2
    assert "first session message" in history_a[0]["content"][0]["text"]
    assert "second session message" in history_b[0]["content"][0]["text"]
