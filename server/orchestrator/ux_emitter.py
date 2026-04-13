from __future__ import annotations

from .constants import OrchestratorEvent, ToolId


def tool_start(tool: str, params: dict) -> dict:
    labels = {
        ToolId.WEB_SEARCH: lambda p: f"Searching for \"{p.get('query', '')}\"...",
        ToolId.MEMORY_SEARCH: lambda p: "Checking memory...",
        ToolId.MEMORY_SAVE: lambda p: "Saving to memory...",
        ToolId.MEMORY_UPDATE: lambda p: "Updating memory...",
        ToolId.URL_SUMMARIZER: lambda p: f"Reading {p.get('url', 'page')}...",
    }
    label = labels.get(tool, lambda p: f"Using {tool}...")(params)
    return {
        "ok": True,
        "event": OrchestratorEvent.TOOL_STATUS,
        "phase": "start",
        "tool": tool,
        "display": label,
    }


def tool_done(tool: str) -> dict:
    return {"ok": True, "event": OrchestratorEvent.TOOL_STATUS, "phase": "done", "tool": tool}


def task_progress(task_id: str, desc: str, step: str) -> dict:
    return {"event": OrchestratorEvent.TASK_PROGRESS, "task_id": task_id, "task_description": desc, "step": step}


def task_complete(task_id: str, desc: str, summary: str) -> dict:
    return {"event": OrchestratorEvent.TASK_COMPLETE, "task_id": task_id, "task_description": desc, "summary": summary}


def task_waiting(task_id: str, desc: str, question: str) -> dict:
    return {"event": OrchestratorEvent.TASK_WAITING, "task_id": task_id, "task_description": desc, "question": question}


def task_error(task_id: str, desc: str, reason: str) -> dict:
    return {"event": OrchestratorEvent.TASK_ERROR, "task_id": task_id, "task_description": desc, "reason": reason}
