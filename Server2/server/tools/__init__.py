from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from server.tools import deep_search as deep_search_mod
from server.tools import web_search as web_search_mod
from server.tools.fetch_url import fetch_url
from server.tools.memory_recall import memory_recall
from server.tools.memory_save import memory_save
from server.tools.registry import ToolEntry, ToolRegistry, ToolResult
from server.tools.runner import ToolRunner
from server.tools.tool_search import tool_search

if TYPE_CHECKING:
    from server.config import Settings


def _tool_settings_partial(settings: Settings) -> dict[str, object]:
    return {
        "tavily_api_key": settings.tavily_api_key,
        "groq_api_key": settings.groq_api_key,
        "allow_dynamic_fallback": True,
        "static_timeout_s": float(settings.deep_search_static_timeout_s),
        "dynamic_timeout_ms": settings.deep_search_dynamic_timeout_ms,
        "min_extract_chars": settings.deep_search_min_extract_chars,
        "max_article_chars": settings.deep_search_max_chars_per_article,
    }


def build_tool_registry(settings: Settings) -> ToolRegistry:
    registry = ToolRegistry()
    tool_partial = partial(_tool_search_bound, registry=registry)

    registry.register(
        ToolEntry(
            name="tool_search",
            capability="main",
            description=(
                "List registered tools and when to use each (discovery only — "
                "does not fetch web pages or news)."
            ),
            args_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "capability": {"type": "string"},
                },
            },
            fn=tool_partial,
            cost_hint="cheap",
            timeout_s=10,
        )
    )

    registry.register(
        ToolEntry(
            name="web_search",
            capability="main",
            description=(
                "Quick web search: short snippets and headlines (seconds). "
                "Use for stocks, news, weather — not for reading full articles."
            ),
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

    research_shared = _tool_settings_partial(settings)

    registry.register(
        ToolEntry(
            name="memory_recall",
            capability="research",
            description="Read a stored user fact by key (for background research).",
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

    registry.register(
        ToolEntry(
            name="fetch_url",
            capability="research",
            description="Fetch and extract readable text from one URL (static first).",
            args_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string"},
                    "dynamic": {"type": "boolean"},
                    "allow_dynamic_fallback": {"type": "boolean"},
                },
            },
            fn=partial(fetch_url, **research_shared),
            cost_hint="heavy",
            timeout_s=90,
        )
    )

    registry.register(
        ToolEntry(
            name="deep_search",
            capability="research",
            description=(
                "Deep research: search then fetch and extract full article text from pages. "
                "Use when the user wants depth, sources, or full reads — slower than web_search."
            ),
            args_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "max_urls": {"type": "integer"},
                    "search_depth": {
                        "type": "string",
                        "enum": ["basic", "advanced"],
                    },
                    "dynamic": {"type": "boolean"},
                    "allow_dynamic_fallback": {"type": "boolean"},
                },
            },
            fn=partial(deep_search_mod.deep_search, **research_shared),
            cost_hint="heavy",
            timeout_s=120,
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
