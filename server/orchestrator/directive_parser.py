from __future__ import annotations

import re
from typing import Any


_DIRECTIVE_RE = re.compile(r"\[(DELEGATE|STOP|ANSWER_TO|MODE_SWITCH)\]([\s\S]*?)(?=\n\[|\Z)", re.IGNORECASE)


def _line_value(block: str, key: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(block)
    return match.group(1).strip() if match else ""


def parse(text: str) -> list[dict[str, Any]]:
    directives: list[dict[str, Any]] = []
    if not text:
        return directives

    for match in _DIRECTIVE_RE.finditer(text):
        dtype = match.group(1).upper()
        body = match.group(2) or ""

        if dtype == "DELEGATE":
            task = _line_value(body, "task")
            capability = _line_value(body, "capability")
            if task and capability:
                directives.append({"type": "DELEGATE", "task": task, "capability": capability})

        elif dtype == "STOP":
            task_id = _line_value(body, "task_id")
            if task_id:
                directives.append({"type": "STOP", "task_id": task_id})

        elif dtype == "ANSWER_TO":
            task_id = _line_value(body, "task_id")
            answer = _line_value(body, "answer")
            if task_id and answer:
                directives.append({"type": "ANSWER_TO", "task_id": task_id, "answer": answer})

        elif dtype == "MODE_SWITCH":
            mode = _line_value(body, "mode").lower()
            if mode in {"conversation", "meeting"}:
                directives.append({"type": "MODE_SWITCH", "mode": mode})

    return directives
