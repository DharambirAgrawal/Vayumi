from __future__ import annotations

from server.tools.registry import ToolEntry, ToolRegistry

# Main-agent tools exposed via llama-server native function calling.
MAIN_OPENAI_TOOL_NAMES = frozenset({"web_search", "memory_save", "memory_recall"})


def entry_to_openai_tool(entry: ToolEntry) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": entry.name,
            "description": entry.description,
            "parameters": entry.args_schema,
        },
    }


def openai_tools_for_main(registry: ToolRegistry) -> list[dict[str, object]]:
    tools: list[dict[str, object]] = []
    for entry in registry.resolve_for_capability("main"):
        if entry.name not in MAIN_OPENAI_TOOL_NAMES:
            continue
        tools.append(entry_to_openai_tool(entry))
    tools.sort(key=lambda item: str(item.get("function", {}).get("name", "")))
    return tools
