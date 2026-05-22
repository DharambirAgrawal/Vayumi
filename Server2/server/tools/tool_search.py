from __future__ import annotations

from server.tools.registry import ToolCard, ToolRegistry, ToolResult


async def tool_search(
    *,
    user_id: str,
    query: str,
    capability: str | None = None,
    registry: ToolRegistry | None = None,
) -> ToolResult:
    del user_id  # discovery is registry-scoped; user_id reserved for future auth filters
    if registry is None:
        return ToolResult(status="error", summary="Tool registry not available")
    cards: list[ToolCard] = registry.search(query, capability=capability)
    return ToolResult(
        status="ok",
        summary=f"Found {len(cards)} tool(s) for {query!r}",
        data={"tools": [card.model_dump() for card in cards]},
    )
