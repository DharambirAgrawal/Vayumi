from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from server.tools import comms_email as comms_email_mod
from server.tools import deep_search as deep_search_mod
from server.tools import fetch_html as fetch_html_mod
from server.tools import summarize_url as summarize_url_mod
from server.tools import web_search as web_search_mod
from server.tools.memory_recall import memory_recall
from server.tools.memory_save import memory_save
from server.tools.productivity_draft import draft_document
from server.tools.registry import ToolEntry, ToolRegistry, ToolResult
from server.tools.runner import ToolRunner
from server.tools.tool_search import tool_search

if TYPE_CHECKING:
    from server.config import Settings

_URL_ARGS_SCHEMA = {
    "type": "object",
    "required": ["url"],
    "properties": {
        "url": {"type": "string"},
        "dynamic": {"type": "boolean"},
        "allow_dynamic_fallback": {"type": "boolean"},
    },
}


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


def _register_tool_search(registry: ToolRegistry, capability: str, tool_partial) -> None:
    registry.register(
        ToolEntry(
            name="tool_search",
            capability=capability,  # type: ignore[arg-type]
            description=(
                f"List tools available to the {capability} sub-agent "
                "(discovery only — does not fetch pages)."
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


def _register_summarize_url(
    registry: ToolRegistry,
    capability: str,
    fetch_kwargs: dict[str, object],
) -> None:
    registry.register(
        ToolEntry(
            name="summarize_url",
            capability=capability,  # type: ignore[arg-type]
            description=(
                "Fetch one URL and return clean article text (trafilatura extraction)."
            ),
            args_schema=dict(_URL_ARGS_SCHEMA),
            fn=partial(summarize_url_mod.summarize_url, **fetch_kwargs),
            cost_hint="heavy",
            timeout_s=90,
        )
    )


def build_tool_registry(settings: Settings) -> ToolRegistry:
    registry = ToolRegistry()
    tool_partial = partial(_tool_search_bound, registry=registry)
    fetch_kwargs = _tool_settings_partial(settings)

    _register_tool_search(registry, "main", tool_partial)

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

    for cap in ("research", "productivity", "comms"):
        _register_tool_search(registry, cap, tool_partial)

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

    _register_summarize_url(registry, "research", fetch_kwargs)
    _register_summarize_url(registry, "productivity", fetch_kwargs)

    registry.register(
        ToolEntry(
            name="fetch_html",
            capability="research",
            description="Fetch raw HTML for one URL (no article extraction).",
            args_schema=dict(_URL_ARGS_SCHEMA),
            fn=partial(fetch_html_mod.fetch_html, **fetch_kwargs),
            cost_hint="heavy",
            timeout_s=90,
        )
    )

    registry.register(
        ToolEntry(
            name="deep_search",
            capability="research",
            description=(
                "Deep research: search the web, then fetch and extract each link. "
                "Best for multi-source depth — slower than web_search."
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
            fn=partial(deep_search_mod.deep_search, **fetch_kwargs),
            cost_hint="heavy",
            timeout_s=120,
        )
    )

    registry.register(
        ToolEntry(
            name="draft_document",
            capability="productivity",
            description="Draft or update a workspace document (requires connected integrations).",
            args_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "instructions": {"type": "string"},
                },
            },
            fn=draft_document,
            risk="write",
            cost_hint="net",
            timeout_s=30,
        )
    )

    registry.register(
        ToolEntry(
            name="read_email",
            capability="comms",
            description="Search or read email messages (requires connected mailbox).",
            args_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
            },
            fn=comms_email_mod.read_email,
            requires_auth=True,
            cost_hint="net",
            timeout_s=30,
        )
    )

    registry.register(
        ToolEntry(
            name="send_email",
            capability="comms",
            description="Send an email (requires confirmation and connected mailbox).",
            args_schema={
                "type": "object",
                "required": ["to", "subject", "body"],
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "confirmed": {"type": "boolean"},
                    "confirmation_id": {"type": "string"},
                },
            },
            fn=comms_email_mod.send_email,
            requires_auth=True,
            requires_confirmation=True,
            risk="send",
            cost_hint="net",
            timeout_s=30,
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
