from __future__ import annotations

from pathlib import Path

from server.subagents.capabilities.bundle import CapabilityBundle

BUNDLE = CapabilityBundle(
    name="productivity",
    prompt_path=Path("prompts/sub/productivity.txt"),
    allowed_tools=frozenset(
        {
            "tool_search",
            "draft_document",
            "summarize_url",
        }
    ),
    tools_executed_as_main=frozenset({"tool_search"}),
)
