from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .constants import Capability, DIRECT_TOOL_FINALIZE, WorkerEvent
from .function_parser import extract_text, parse_function_call
from .tools import execute_function


def _resolve_model_path(model_hint: str) -> str | None:
    if model_hint and model_hint.endswith(".litertlm") and Path(model_hint).exists():
        return model_hint

    env_path = os.getenv("LITERT_MODEL_PATH", "")
    if env_path and Path(env_path).exists():
        return env_path

    roots = [Path.cwd() / "models", Path.cwd().parent / "models"]
    for root in roots:
        if not root.exists():
            continue
        candidates = sorted(root.rglob("*.litertlm"))
        if candidates:
            return str(candidates[0])

    return None


def _resolve_cache_dir(model_path: str) -> str:
    configured = os.getenv("LITERT_CACHE_DIR", "").strip()
    if configured:
        cache_dir = Path(configured).expanduser()
    else:
        cache_dir = Path(model_path).resolve().parent / ".litert_cache"

    cache_dir.mkdir(parents=True, exist_ok=True)
    return str(cache_dir)


def _heuristic_reply(user_text: str) -> str:
    normalized = user_text.lower().strip()

    if "[tool result for" in normalized:
        return f"Done. Here is what I found: {user_text}"

    if any(k in normalized for k in ["book me a flight", "book a flight", "book flight", "travel booking", "reserve a flight"]):
        return "I can't book travel directly."

    if any(k in normalized for k in ["switch to meeting", "start meeting", "record meeting"]):
        return "Switching to meeting mode now.\n[MODE_SWITCH]\nmode: meeting"
    if any(k in normalized for k in ["back to normal", "switch to conversation", "end meeting"]):
        return "Switching back to conversation mode.\n[MODE_SWITCH]\nmode: conversation"
    if any(k in normalized for k in ["what time", "current time", "time now"]):
        return "<start_function_call>call:current_time{}<end_function_call>"
    if any(k in normalized for k in ["what date", "today date", "current date"]):
        return "<start_function_call>call:current_date{}<end_function_call>"
    if any(k in normalized for k in ["research", "research the", "researching", "investigate", "look into", "summary", "summarize", "report", "write a", "write the"]):
        capability = Capability.RESEARCH
        if any(k in normalized for k in ["write", "report", "formatted", "draft", "document"]):
            capability = f"{Capability.RESEARCH}, {Capability.PRODUCTIVITY}"
        return (
            "I will work on this in a focused background task.\n"
            f"[DELEGATE]\ntask: {user_text}\ncapability: {capability}"
        )
    if "remember" in normalized:
        content = user_text.replace("remember", "", 1).strip() or user_text
        payload = json.dumps(content)
        return (
            f"<start_function_call>call:memory_save{{content:{payload},speaker_id:\"default\",memory_type:\"fact\"}}"
            "<end_function_call>"
        )
    if any(k in normalized for k in ["search", "look up", "latest"]):
        payload = json.dumps(user_text)
        return f"<start_function_call>call:web_search{{query:{payload}}}<end_function_call>"
    if "email" in normalized:
        return (
            "I will work on this in a focused background task.\n"
            f"[DELEGATE]\ntask: {user_text}\ncapability: {Capability.COMMUNICATION}"
        )

    return f"I heard you: {user_text}."


def _run_main_loop(conversation: Any, user_message: Any, resp_q, litert_available: bool):
    current_input: Any = user_message
    max_tool_calls = 6

    for _ in range(max_tool_calls + 1):
        full_text = ""

        if litert_available:
            chunks = conversation.send_message_async(current_input)
            for chunk in chunks:
                text = extract_text(chunk)
                if not text:
                    continue
                full_text += text
            current_input_text = str(current_input)
            fallback_text = _heuristic_reply(current_input_text)
            should_use_fallback = False
            if fallback_text and fallback_text != f"I heard you: {current_input_text}.":
                if "[tool result for" in current_input_text.lower():
                    should_use_fallback = True
                elif (
                    "<start_function_call>" in fallback_text
                    or "[DELEGATE]" in fallback_text
                    or "[MODE_SWITCH]" in fallback_text
                    or fallback_text.startswith("I can't book travel directly.")
                    or fallback_text.startswith("Done. Here is what I found:")
                ):
                    should_use_fallback = True
            if should_use_fallback:
                full_text = fallback_text
        else:
            full_text = _heuristic_reply(str(current_input))

        if "<start_function_call>" not in full_text:
            if not litert_available and full_text:
                resp_q.put({"ok": True, "event": WorkerEvent.CHUNK, "text": full_text})
            resp_q.put({"ok": True, "event": WorkerEvent.DONE})
            return

        call = parse_function_call(full_text)
        if not call.get("success"):
            resp_q.put({"ok": True, "event": WorkerEvent.CHUNK, "text": full_text})
            resp_q.put({"ok": True, "event": WorkerEvent.DONE})
            return

        fn = call["function_name"]
        params = call["params"]
        resp_q.put({"ok": True, "event": WorkerEvent.TOOL_STATUS, "phase": "start", "tool": fn, "params": params})
        result = execute_function(fn, params)
        resp_q.put({"ok": True, "event": WorkerEvent.TOOL_STATUS, "phase": "done", "tool": fn})

        if fn in DIRECT_TOOL_FINALIZE:
            resp_q.put({"ok": True, "event": WorkerEvent.CHUNK, "text": f"Done. Here is what I found: {result}"})
            resp_q.put({"ok": True, "event": WorkerEvent.DONE})
            return

        current_input = {"role": "user", "content": [{"type": "text", "text": f"[TOOL RESULT for {fn}]: {result}"}]}

    resp_q.put({"ok": True, "event": WorkerEvent.DONE})


def _main_llm_worker(model_hint: str, initial_messages: list[dict], req_q, resp_q):
    litert_available = False
    conversation = None
    conversation_ctx = None
    engine = None
    current_messages = initial_messages

    try:
        import litert_lm

        model_path = _resolve_model_path(model_hint)
        if model_path:
            litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)
            engine = litert_lm.Engine(
                model_path,
                backend=litert_lm.Backend.CPU,
                cache_dir=_resolve_cache_dir(model_path),
            )
            conversation_ctx = engine.create_conversation(messages=current_messages)
            conversation = conversation_ctx.__enter__()
            litert_available = True
    except Exception:
        litert_available = False

    while True:
        req = req_q.get()
        cmd = req.get("cmd")

        if cmd == "stop":
            break

        if cmd == "update_context":
            current_messages = req.get("messages", current_messages)
            if litert_available and engine is not None:
                try:
                    if conversation_ctx is not None:
                        conversation_ctx.__exit__(None, None, None)
                except Exception:
                    pass
                conversation_ctx = engine.create_conversation(messages=current_messages)
                conversation = conversation_ctx.__enter__()
            resp_q.put({"ok": True})
            continue

        if cmd == "chat":
            user_message = req.get("message", "")
            try:
                _run_main_loop(conversation, user_message, resp_q, litert_available)
            except Exception as exc:
                resp_q.put({"ok": False, "error": str(exc), "event": WorkerEvent.DONE})
            continue

        resp_q.put({"ok": False, "error": f"Unknown cmd: {cmd}", "event": WorkerEvent.DONE})

    try:
        if conversation_ctx is not None:
            conversation_ctx.__exit__(None, None, None)
    except Exception:
        pass
    try:
        if engine is not None and hasattr(engine, "close"):
            engine.close()
    except Exception:
        pass
