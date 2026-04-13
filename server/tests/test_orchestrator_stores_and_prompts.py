from __future__ import annotations

import sys
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from orchestrator.history_store import HistoryStore
from orchestrator.meeting_store import MeetingStore
from orchestrator.prompt_builder import build_main_messages, build_turn_context
from orchestrator.session_store import SessionStore, TaskSession


class _FakeWorker:
    def __init__(self):
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def test_history_store_compression_keeps_recent() -> None:
    store = HistoryStore()
    sid = "s1"
    large = "x" * 1500

    for i in range(40):
        store.append(sid, f"u{i} {large}", f"a{i} {large}")

    compressed = store.maybe_compress(sid)
    turns = store.get(sid)

    assert compressed
    assert turns[0]["role"] == "system"
    assert "[EARLIER CONVERSATION SUMMARY]" in turns[0]["content"][0]["text"]
    assert len(turns) <= 13  # summary + last 12 messages (6 turns)


def test_session_store_active_block_and_timeouts() -> None:
    store = SessionStore()
    worker = _FakeWorker()
    task = TaskSession(
        task_id="task_a",
        description="Collect docs",
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
    )

    store.add("spk", task)
    store.update_step("spk", "task_a", "Searching")
    block = store.get_active_tasks_block("spk")
    assert "running" in block
    assert "Searching" in block

    expired = store.expire_timeouts("spk")
    assert expired == ["task_a"]

    store.stop_and_remove("spk", "task_a")
    assert worker.stopped is True


def test_meeting_store_append_format_clear() -> None:
    store = MeetingStore()
    store.init("session-x")
    store.append("session-x", "Speaker A: kickoff")
    store.append("session-x", "Speaker B: response")
    assert "Speaker A" in store.get_formatted("session-x")

    store.clear("session-x")
    assert store.get_formatted("session-x") == ""


def test_prompt_builder_turn_context_and_messages() -> None:
    ctx = build_turn_context(
        mem_context="Known preference: concise",
        active_tasks="[ACTIVE TASKS]\ntask_1: \"x\" - running",
        pending_results=[{"type": "DONE", "description": "x", "message": "ok"}],
        vayumi_state={"mode": "conversation", "is_ai_speaking": False},
        meeting_transcript=None,
    )
    text = ctx["content"][0]["text"]
    assert "[MEMORY]" in text
    assert "[ACTIVE TASKS]" in text
    assert "[TASK RESULTS THIS TURN]" in text
    assert "[SESSION STATE]" in text

    messages = build_main_messages(
        session_id="s2",
        speaker_id="spk",
        user_profile="prefers short replies",
        mem_context="memory",
        active_tasks="",
        pending_results=[],
        vayumi_state={},
        meeting_transcript=None,
    )
    assert messages[0]["role"] == "developer"
    assert messages[1]["role"] == "system"
