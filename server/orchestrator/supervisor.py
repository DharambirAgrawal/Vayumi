from __future__ import annotations

import asyncio
import re
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from runtime_constants import InterruptPolicy, RespondVia
from .constants import OrchestratorEvent, TaskSignal, WorkerEvent
from . import directive_parser
from .capability_router import resolve
from .context_loader import load_skill_docs
from .history_store import history_store
from .main_agent import _main_llm_worker
from .meeting_store import meeting_store
from .prompt_builder import build_main_messages, build_sub_agent_prompt
from .session_store import TaskSession, session_store
from .signal_bus import signal_bus
from .sub_agent import _sub_agent_worker
from .summarizer import run_on_task, run_on_turns
from .tools import get_all_tool_ids
from .worker_base import LiteRTWorker
from . import ux_emitter


# Dev/test policy: give sub-agents full tool access.
SUBAGENT_FULL_TOOL_ACCESS = True


def _ensure_repo_root() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.append(repo_root_str)


def _safe_get_memory_context(transcript: str, speaker_id: str) -> tuple[str, str]:
    try:
        _ensure_repo_root()
        from memory import MemorySystem

        mem = MemorySystem(speaker_id=speaker_id)
        search = mem.search(transcript, speaker_id=speaker_id, top_k=5)
        profile = mem.personalization.to_system_prompt(mem.get_user_model(speaker_id))
        return search.context, profile
    except Exception:
        return "", ""


def _safe_add_turn_and_flush(speaker_id: str, transcript: str) -> None:
    try:
        _ensure_repo_root()
        from memory import MemorySystem

        mem = MemorySystem(speaker_id=speaker_id)
        mem.add_turn(speaker_id, transcript)
        mem.flush_session()
    except Exception:
        return


class InterruptStore:
    def __init__(self):
        self._flags: dict[str, bool] = {}

    def set_interrupted(self, session_id: str, state: bool) -> None:
        self._flags[session_id] = state

    def clear(self, session_id: str) -> None:
        self._flags.pop(session_id, None)

    def is_interrupted(self, session_id: str) -> bool:
        return self._flags.get(session_id, False)


class WorkerStore:
    def __init__(self):
        self._workers: dict[str, LiteRTWorker] = {}

    def get(self, session_id: str) -> Optional[LiteRTWorker]:
        return self._workers.get(session_id)

    def ensure(self, session_id: str, model_hint: str, messages: list[dict]) -> LiteRTWorker:
        worker = self._workers.get(session_id)
        if worker and worker.is_alive():
            return worker

        worker = LiteRTWorker(
            worker_fn=_main_llm_worker,
            worker_args=(model_hint, messages),
        )
        worker.start()
        self._workers[session_id] = worker
        return worker

    def stop(self, session_id: str) -> None:
        worker = self._workers.pop(session_id, None)
        if worker:
            worker.stop()


interrupt_store = InterruptStore()
main_worker_store = WorkerStore()
session_mode_store: dict[str, str] = {}


def _generate_task_id() -> str:
    return f"task_{uuid.uuid4().hex[:6]}"


def _is_explicit_question(text: str) -> bool:
    stripped = text.strip().lower()
    if "?" in stripped:
        return True
    return any(stripped.startswith(prefix) for prefix in ["what", "why", "how", "when", "who", "can you", "please"]) 


def _strip_directives(text: str) -> str:
    return re.sub(r"\[(DELEGATE|STOP|ANSWER_TO|MODE_SWITCH)\][\s\S]*?(?=\n\[|\Z)", "", text, flags=re.IGNORECASE).strip()


async def _apply_mode_switch(session_id: str, speaker_id: str, mode: str) -> None:
    session_mode_store[session_id] = mode
    if mode == "meeting":
        meeting_store.init(session_id)
    else:
        transcript = meeting_store.get_formatted(session_id)
        if transcript:
            await run_on_turns(
                speaker_id,
                [{"role": "user", "content": [{"type": "text", "text": transcript}]}],
            )
        meeting_store.clear(session_id)


def _spawn_sub_agent(speaker_id: str, directive: dict[str, Any], model_hint: str) -> None:
    task_id = _generate_task_id()
    capabilities = [c.strip() for c in str(directive.get("capability", "")).split(",") if c.strip()]
    tool_ids = get_all_tool_ids() if SUBAGENT_FULL_TOOL_ACCESS else resolve(capabilities)
    if not tool_ids:
        return

    task_description = str(directive.get("task", ""))
    skill_doc = load_skill_docs(tool_ids)
    developer_prompt = build_sub_agent_prompt(task_id, task_description, tool_ids, skill_doc, max_steps=12)

    worker = LiteRTWorker(
        worker_fn=_sub_agent_worker,
        worker_args=(model_hint, task_id, developer_prompt, tool_ids, signal_bus.get_queue(speaker_id)),
    )
    worker.start()

    session_store.add(
        speaker_id,
        TaskSession(
            task_id=task_id,
            description=task_description,
            capability=",".join(capabilities),
            status="running",
            tool_ids=tool_ids,
            worker=worker,
            pending_question=None,
            step_log=[],
            last_step_message="",
            created_at=time.time(),
            step_count=0,
            max_steps=12,
            timeout_at=time.time() + 180,
        ),
    )
    worker.request({"cmd": "run", "message": {"role": "user", "content": [{"type": "text", "text": "Begin now."}]}})


def _stop_sub_agent(speaker_id: str, task_id: str) -> None:
    session_store.stop_and_remove(speaker_id, task_id)


def _resume_sub_agent(speaker_id: str, task_id: str, answer: str) -> None:
    task = session_store.get(speaker_id, task_id)
    if not task:
        return
    task.status = "running"
    task.pending_question = None
    task.worker.request(
        {
            "cmd": "run",
            "message": {"role": "user", "content": [{"type": "text", "text": answer}]},
        }
    )


async def handle_turn(transcript: str, session_id: str, context: dict[str, Any], model_hint: str) -> AsyncIterator[dict[str, Any]]:
    speaker_id = context.get("speaker_id") or session_id
    input_mode = context.get("input_mode", "chat")
    vayumi_state = context.get("vayumi_state", {})
    session_mode = session_mode_store.get(session_id, "conversation")

    respond_via = RespondVia.VOICE_AND_CHAT if input_mode == "voice" else RespondVia.CHAT_ONLY
    interrupt_policy = InterruptPolicy.REPLACE if input_mode == "voice" else InterruptPolicy.QUEUE

    history_store.maybe_compress(session_id)

    for task_id in session_store.expire_timeouts(speaker_id):
        session_store.mark_closed(speaker_id, task_id, status="error")
        session_store.stop_and_remove(speaker_id, task_id)

    signals = signal_bus.drain(speaker_id)
    pending_results: list[dict[str, Any]] = []
    streamed_events: list[dict[str, Any]] = []

    for sig in signals:
        task = session_store.get(speaker_id, sig.get("task_id", ""))
        if not task:
            continue

        sig_type = sig.get("type")
        if sig_type == TaskSignal.STEP:
            session_store.update_step(speaker_id, task.task_id, sig.get("message", ""))
            streamed_events.append(ux_emitter.task_progress(task.task_id, task.description, sig.get("message", "")))
        elif sig_type == TaskSignal.NEEDS_INFO:
            session_store.mark_paused(speaker_id, task.task_id, sig.get("message", ""))
            streamed_events.append(ux_emitter.task_waiting(task.task_id, task.description, sig.get("message", "")))
            pending_results.append({**sig, "description": task.description})
        elif sig_type in {TaskSignal.DONE, TaskSignal.ERROR, TaskSignal.CAPABILITY_GAP}:
            session_store.mark_closed(speaker_id, task.task_id, status="done" if sig_type == TaskSignal.DONE else "error")
            if sig_type == TaskSignal.DONE:
                streamed_events.append(ux_emitter.task_complete(task.task_id, task.description, sig.get("message", "")))
            else:
                streamed_events.append(ux_emitter.task_error(task.task_id, task.description, sig.get("message", "")))
            pending_results.append({**sig, "description": task.description})
            asyncio.create_task(run_on_task(speaker_id, task.description, sig.get("message", ""), sig.get("step_log", [])))
            session_store.stop_and_remove(speaker_id, task.task_id)

    for event in streamed_events:
        yield event

    if session_mode == "meeting":
        meeting_store.append(session_id, transcript)
        if not _is_explicit_question(transcript):
            return

    mem_context, user_profile = _safe_get_memory_context(transcript, speaker_id)
    meeting_transcript = meeting_store.get_formatted(session_id) if session_mode == "meeting" else None

    updated_messages = build_main_messages(
        session_id=session_id,
        speaker_id=speaker_id,
        user_profile=user_profile,
        mem_context=mem_context,
        active_tasks=session_store.get_active_tasks_block(speaker_id),
        pending_results=pending_results,
        vayumi_state=vayumi_state,
        meeting_transcript=meeting_transcript,
    )

    main_worker = main_worker_store.ensure(session_id, model_hint, updated_messages)
    main_worker.request({"cmd": "update_context", "messages": updated_messages}, timeout=10)

    yield {"event": OrchestratorEvent.AGENT_THINKING}

    response_text = ""
    for chunk in main_worker.stream({"cmd": "chat", "message": transcript}, timeout_s=20):
        if interrupt_store.is_interrupted(session_id):
            break
        if not chunk.get("ok", True):
            yield {"event": OrchestratorEvent.ERROR, "message": chunk.get("error", "Unknown worker error")}
            return

        event_type = chunk.get("event")
        if event_type == WorkerEvent.TOOL_STATUS:
            if chunk.get("phase") == "start":
                yield ux_emitter.tool_start(chunk.get("tool", "tool"), chunk.get("params", {}))
            else:
                yield ux_emitter.tool_done(chunk.get("tool", "tool"))
        elif event_type == WorkerEvent.CHUNK:
            response_text += str(chunk.get("text", ""))
        elif event_type == WorkerEvent.DONE:
            break

    if interrupt_store.is_interrupted(session_id):
        interrupt_store.clear(session_id)
        return

    directives = directive_parser.parse(response_text)
    user_text = _strip_directives(response_text)

    for directive in directives:
        dtype = directive.get("type")
        if dtype == "DELEGATE":
            _spawn_sub_agent(speaker_id, directive, model_hint)
        elif dtype == "STOP":
            _stop_sub_agent(speaker_id, directive.get("task_id", ""))
        elif dtype == "ANSWER_TO":
            _resume_sub_agent(speaker_id, directive.get("task_id", ""), directive.get("answer", ""))
        elif dtype == "MODE_SWITCH":
            await _apply_mode_switch(session_id, speaker_id, directive.get("mode", "conversation"))

    if user_text:
        yield {
            "event": OrchestratorEvent.CHATBOT_RESPONSE,
            "text": user_text,
            "respond_via": respond_via,
            "interrupt_policy": interrupt_policy,
        }

    yield {"event": OrchestratorEvent.AGENT_RESPONSE_END}

    if user_text:
        history_store.append(session_id, transcript, user_text)

    await asyncio.to_thread(_safe_add_turn_and_flush, speaker_id, transcript)


async def handle_interrupt(session_id: str) -> None:
    interrupt_store.set_interrupted(session_id, True)
