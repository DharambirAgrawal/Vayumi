from __future__ import annotations

from server.memory import facts
from server.tools.registry import ToolResult


async def memory_recall(
    *,
    user_id: str,
    key: str,
    chain: bool = False,
) -> ToolResult:
    key = key.strip()
    if not key:
        return ToolResult(status="error", summary="key is required", retryable=False)

    if chain:
        rows = await facts.get_chain(user_id, key)
        if not rows:
            payload: object = []
            summary = f"No history for key={key}"
        else:
            payload = [
                {
                    "active": row.active,
                    "value": row.value,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
            summary = f"Chain for {key} ({len(rows)} version(s))"
        return ToolResult(
            status="ok",
            summary=summary,
            data={"key": key, "chain": payload},
        )

    record = await facts.get_fact(user_id, key)
    if record is None:
        return ToolResult(
            status="ok",
            summary=f"No active fact for key={key}",
            data={"key": key, "value": None},
        )
    return ToolResult(
        status="ok",
        summary=f"Recalled {key}",
        data={"key": key, "value": record.value},
    )
