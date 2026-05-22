from __future__ import annotations

import pytest

from server.config import Settings
from server.tools import build_tool_registry
from server.tools.tool_search import tool_search


@pytest.mark.asyncio
async def test_tool_search_returns_cards() -> None:
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    registry = build_tool_registry(settings)
    result = await tool_search(
        user_id="u1",
        query="memory",
        capability="main",
        registry=registry,
    )
    assert result.status == "ok"
    tools = result.data.get("tools", [])
    assert any(t["name"] == "memory_recall" for t in tools)
