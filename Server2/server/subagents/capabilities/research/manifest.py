from __future__ import annotations

from pathlib import Path

from server.subagents.capabilities.bundle import CapabilityBundle

BUNDLE = CapabilityBundle(
    name="research",
    prompt_path=Path("prompts/sub/research.txt"),
    allowed_tools=frozenset(
        {
            "tool_search",
            "web_search",
            "summarize_url",
            "fetch_html",
            "deep_search",
            "memory_recall",
        }
    ),
    tools_executed_as_main=frozenset({"tool_search", "web_search"}),
)
