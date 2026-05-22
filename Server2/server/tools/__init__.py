from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from server.tools import web_search as web_search_mod
from server.tools.memory_recall import memory_recall
from server.tools.memory_save import memory_save
from server.tools.registry import ToolEntry, ToolRegistry, ToolResult
from server.tools.runner import ToolRunner
from server.tools.tool_search import tool_search

if TYPE_CHECKING:
    from server.config import Settings


def build_tool_registry(settings: Settings) -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(
        ToolEntry(
            name="tool_search",
            capability="main",
            description="Discover registered tools by keyword (compact cards only).",
            args_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "capability": {"type": "string"},
                },
            },
            fn=partial(_tool_search_bound, registry=registry),
            cost_hint="cheap",
            timeout_s=10,
        )
    )

    registry.register(
        ToolEntry(
            name="web_search",
            capability="main",
            description="Search the web (Tavily when configured, DuckDuckGo fallback).",
            args_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "search_depth": {
                        "type": "string",
                        "enum": ["basic", "advanced"],
                    },
                },
            },
            fn=partial(web_search_mod.web_search, tavily_api_key=settings.tavily_api_key),
            cost_hint="net",
            timeout_s=30,
        )
    )

    registry.register(
        ToolEntry(
            name="memory_save",
            capability="main",
            description="Persist a versioned fact for this user.",
            args_schema={
                "type": "object",
                "required": ["key", "value"],
                "properties": {
                    "key": {"type": "string"},
                    "value": {},
                    "source": {"type": "string"},
                },
            },
            fn=memory_save,
            risk="write",
            cost_hint="cheap",
            timeout_s=15,
        )
    )

    registry.register(
        ToolEntry(
            name="memory_recall",
            capability="main",
            description="Read an active fact or full supersession chain by key.",
            args_schema={
                "type": "object",
                "required": ["key"],
                "properties": {
                    "key": {"type": "string"},
                    "chain": {"type": "boolean"},
                },
            },
            fn=memory_recall,
            cost_hint="cheap",
            timeout_s=15,
        )
    )

    return registry


def build_tool_runner(registry: ToolRegistry) -> ToolRunner:
    return ToolRunner(registry)


def init_tools(settings: Settings) -> tuple[ToolRegistry, ToolRunner]:
    registry = build_tool_registry(settings)
    return registry, build_tool_runner(registry)


async def _tool_search_bound(
    *,
    user_id: str,
    query: str,
    capability: str | None = None,
    registry: ToolRegistry,
) -> ToolResult:
    return await tool_search(
        user_id=user_id,
        query=query,
        capability=capability,
        registry=registry,
    )
