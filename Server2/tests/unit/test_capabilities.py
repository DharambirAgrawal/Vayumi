from __future__ import annotations

import pytest

from server.config import Settings
from server.subagents.capabilities import (
    load_capability,
    render_tool_cards,
    render_tool_cards_for_bundle,
    resolve_tool_entries,
)
from server.tools import build_tool_registry
from server.tools.registry import ToolEntry, ToolResult


async def _noop(*, user_id: str) -> ToolResult:
    del user_id
    return ToolResult(status="ok", summary="ok")


def test_load_capability_research() -> None:
    bundle = load_capability("research")
    assert bundle.name == "research"
    assert "deep_search" in bundle.allowed_tools
    assert "summarize_url" in bundle.allowed_tools
    assert "fetch_html" in bundle.allowed_tools
    assert "fetch_url" not in bundle.allowed_tools


def test_unknown_capability_raises() -> None:
    with pytest.raises(ValueError, match="unknown"):
        load_capability("unknown")


def test_render_tool_cards_compact() -> None:
    entry = ToolEntry(
        name="summarize_url",
        capability="research",
        description="Extract article text.",
        args_schema={"type": "object", "properties": {}},
        fn=_noop,
    )
    block = render_tool_cards([entry])
    assert "summarize_url" in block
    assert "Extract article" in block


def test_resolve_tool_entries_only_bundle_tools() -> None:
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    registry = build_tool_registry(settings)
    bundle = load_capability("research")
    entries = resolve_tool_entries(registry, bundle)
    names = {e.name for e in entries}
    assert names <= bundle.allowed_tools
    assert "deep_search" in names
    assert "web_search" in names
    assert "fetch_url" not in names


def test_productivity_bundle_excludes_research_only_tools() -> None:
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    registry = build_tool_registry(settings)
    bundle = load_capability("productivity")
    names = {e.name for e in resolve_tool_entries(registry, bundle)}
    assert "deep_search" not in names
    assert "draft_document" in names
    assert "summarize_url" in names


def test_comms_send_email_requires_confirmation_flag() -> None:
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    registry = build_tool_registry(settings)
    entry = registry.get("send_email", "comms")
    assert entry is not None
    assert entry.requires_confirmation is True


def test_render_tool_cards_for_bundle_matches_allowed() -> None:
    settings = Settings(
        database_url="postgresql://x@localhost/x",
        redis_url="redis://localhost",
    )
    registry = build_tool_registry(settings)
    bundle = load_capability("research")
    block = render_tool_cards_for_bundle(registry, bundle)
    assert "deep_search" in block
    assert "fetch_html" in block
    assert "fetch_url" not in block
