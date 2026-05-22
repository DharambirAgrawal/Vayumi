from __future__ import annotations

import json
from typing import Any

from server.memory import facts
from server.tools.registry import ToolResult


async def memory_save(
    *,
    user_id: str,
    key: str,
    value: Any,
    source: str = "tool",
) -> ToolResult:
    key = key.strip()
    if not key:
        return ToolResult(status="error", summary="key is required", retryable=False)
    await facts.set_fact(user_id, key, value, source)
    preview = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return ToolResult(
        status="ok",
        summary=f"Saved fact {key}",
        data={"key": key, "value": preview},
    )
