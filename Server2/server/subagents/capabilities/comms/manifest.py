from __future__ import annotations

from pathlib import Path

from server.subagents.capabilities.bundle import CapabilityBundle

BUNDLE = CapabilityBundle(
    name="comms",
    prompt_path=Path("prompts/sub/comms.txt"),
    allowed_tools=frozenset(
        {
            "tool_search",
            "read_email",
            "send_email",
        }
    ),
    tools_executed_as_main=frozenset({"tool_search"}),
)
