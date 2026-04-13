from __future__ import annotations

import json
import os
from pathlib import Path

from .constants import TaskSignal, WorkerEvent
from .function_parser import extract_text, parse_function_call
from .tools import execute_function

REPORT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "report",
        "description": "Your only output channel. Never write plain-text final answers.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "STEP, DONE, NEEDS_INFO, ERROR, or CAPABILITY_GAP",
                },
                "message": {"type": "string", "description": "Status message."},
            },
            "required": ["status", "message"],
        },
    },
}


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


def _sub_agent_worker(
    model_hint: str,
    task_id: str,
    developer_prompt: str,
    tool_ids: list[str],
    signal_q,
    req_q,
    resp_q,
):
    litert_available = False
    conversation = None

    try:
        import litert_lm

        model_path = _resolve_model_path(model_hint)
        if model_path:
            litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)
            with litert_lm.Engine(
                model_path,
                backend=litert_lm.Backend.CPU,
                cache_dir=_resolve_cache_dir(model_path),
            ) as engine:
                messages = [{"role": "developer", "content": [{"type": "text", "text": developer_prompt}]}]
                with engine.create_conversation(messages=messages) as conv:
                    conversation = conv
                    litert_available = True
                    _sub_agent_loop(task_id, tool_ids, signal_q, req_q, resp_q, conversation, litert_available)
                    return
    except Exception:
        litert_available = False

    _sub_agent_loop(task_id, tool_ids, signal_q, req_q, resp_q, conversation, litert_available)


def _sub_agent_loop(task_id, tool_ids, signal_q, req_q, resp_q, conversation, litert_available: bool):
    step_log: list[str] = []
    step_count = 0
    max_steps = 12

    while True:
        req = req_q.get()
        cmd = req.get("cmd")

        if cmd == "stop":
            signal_q.put({"type": TaskSignal.ERROR, "task_id": task_id, "message": "Cancelled", "step_log": step_log})
            resp_q.put({"ok": True, "event": WorkerEvent.DONE})
            return

        if cmd != "run":
            continue

        user_message = req.get("message", "Begin")

        if not litert_available:
            if not tool_ids:
                signal_q.put(
                    {
                        "type": TaskSignal.CAPABILITY_GAP,
                        "task_id": task_id,
                        "message": "No tools available for this task.",
                        "step_log": [],
                    }
                )
                resp_q.put({"ok": True, "event": WorkerEvent.DONE})
                return

            tool = tool_ids[0]
            signal_q.put({"type": TaskSignal.STEP, "task_id": task_id, "message": f"Using {tool}", "tool": tool})
            result = execute_function(tool, {"query": str(user_message)})
            signal_q.put(
                {
                    "type": TaskSignal.DONE,
                    "task_id": task_id,
                    "message": f"Finished task with {tool}: {result}",
                    "step_log": step_log,
                }
            )
            resp_q.put({"ok": True, "event": WorkerEvent.DONE})
            return

        current_input = user_message
        done = False

        while not done and step_count < max_steps:
            step_count += 1
            response = conversation.send_message(current_input)
            text = extract_text(response)

            if "<start_function_call>" not in text:
                current_input = {
                    "role": "user",
                    "content": [{"type": "text", "text": "Use report() to continue."}],
                }
                continue

            call = parse_function_call(text)
            if not call.get("success"):
                signal_q.put({"type": TaskSignal.ERROR, "task_id": task_id, "message": call.get("error", "parse error")})
                resp_q.put({"ok": True, "event": WorkerEvent.DONE})
                done = True
                break

            fn = call["function_name"]
            params = call["params"]
            step_log.append(f"[CALL] {fn}({json.dumps(params, default=str)})")

            if fn != "report":
                signal_q.put({"type": TaskSignal.STEP, "task_id": task_id, "message": f"Using {fn}", "tool": fn})

            if fn == "report":
                status = str(params.get("status", "STEP"))
                message = str(params.get("message", ""))
                signal_q.put(
                    {
                        "type": status,
                        "task_id": task_id,
                        "message": message,
                        "step_log": step_log if status in {TaskSignal.DONE, TaskSignal.ERROR, TaskSignal.CAPABILITY_GAP} else [],
                    }
                )
                if status in {TaskSignal.DONE, TaskSignal.ERROR, TaskSignal.CAPABILITY_GAP}:
                    resp_q.put({"ok": True, "event": WorkerEvent.DONE})
                    done = True
                    break
                if status == TaskSignal.NEEDS_INFO:
                    resp_q.put({"ok": True, "event": WorkerEvent.PAUSED})
                    done = True
                    break
                current_input = {"role": "user", "content": [{"type": "text", "text": "Noted. Continue."}]}
                continue

            result = execute_function(fn, params)
            current_input = {
                "role": "user",
                "content": [{"type": "text", "text": f"[TOOL RESULT for {fn}]: {result}"}],
            }

        if step_count >= max_steps and not done:
            signal_q.put(
                {
                    "type": TaskSignal.ERROR,
                    "task_id": task_id,
                    "message": "Hit maximum step limit.",
                    "step_log": step_log,
                }
            )
            resp_q.put({"ok": True, "event": WorkerEvent.DONE})
            return
