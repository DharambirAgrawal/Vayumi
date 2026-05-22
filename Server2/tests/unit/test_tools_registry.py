from __future__ import annotations

import pytest

from server.tools.registry import ToolEntry, ToolRegistry, ToolResult, validate_tool_args


async def _noop_tool(*, user_id: str) -> ToolResult:
    del user_id
    return ToolResult(status="ok", summary="ok")


def test_registry_unique_names() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolEntry(
            name="alpha",
            capability="main",
            description="first",
            args_schema={"type": "object", "properties": {}},
            fn=_noop_tool,
        )
    )
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(
            ToolEntry(
                name="alpha",
                capability="main",
                description="dup",
                args_schema={"type": "object", "properties": {}},
                fn=_noop_tool,
            )
        )


def test_resolve_for_capability_main_only() -> None:
    from server.config import Settings

    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    from server.tools import build_tool_registry

    registry = build_tool_registry(settings)
    main_tools = registry.resolve_for_capability("main")
    names = {entry.name for entry in main_tools}
    assert names == {"tool_search", "web_search", "memory_save", "memory_recall"}
    assert registry.resolve_for_capability("research") == []


def test_registry_search_filters() -> None:
    from server.config import Settings
    from server.tools import build_tool_registry

    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    registry = build_tool_registry(settings)
    cards = registry.search("web", capability="main")
    assert any(card.name == "web_search" for card in cards)


def test_validate_tool_args_required() -> None:
    schema = {
        "type": "object",
        "required": ["query"],
        "properties": {"query": {"type": "string"}},
    }
    assert validate_tool_args(schema, {}) is not None
    assert validate_tool_args(schema, {"query": "ai"}) is None
