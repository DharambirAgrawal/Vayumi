"""Always-on MCP that returns the current date and time."""

from __future__ import annotations

from datetime import datetime, timezone


async def execute(params: dict, user_id: str) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "success": True,
        "result": now.isoformat(),
        "timezone": "UTC",
    }


def register_handlers(mcp_runner, **_kwargs) -> None:
    mcp_runner.register_handler("get_datetime", execute)