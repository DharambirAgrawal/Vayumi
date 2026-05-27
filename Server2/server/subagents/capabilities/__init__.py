from __future__ import annotations

from server.subagents.capabilities.bundle import CapabilityBundle
from server.subagents.capabilities.comms.manifest import BUNDLE as COMMS_BUNDLE
from server.subagents.capabilities.productivity.manifest import BUNDLE as PRODUCTIVITY_BUNDLE
from server.subagents.capabilities.research.manifest import BUNDLE as RESEARCH_BUNDLE
from server.tools.registry import ToolEntry, ToolRegistry

_BUNDLES: dict[str, CapabilityBundle] = {
    "research": RESEARCH_BUNDLE,
    "productivity": PRODUCTIVITY_BUNDLE,
    "comms": COMMS_BUNDLE,
}


def load_capability(name: str) -> CapabilityBundle:
    key = name.strip().lower()
    bundle = _BUNDLES.get(key)
    if bundle is None:
        raise ValueError(f"unknown capability: {name}")
    return bundle


def list_capabilities() -> list[str]:
    return sorted(_BUNDLES.keys())


def render_tool_cards(entries: list[ToolEntry]) -> str:
    """Compact tool descriptions injected into the sub-agent system prompt."""
    if not entries:
        return "Tools: (none registered for this capability yet)"

    by_name = {entry.name: entry for entry in entries}
    lines = [
        "Tools — call only via "
        '[DELEGATE capability=<this capability> goal="..." '
        'payload={"tool":"NAME","args":{...}}]:',
        "",
        "| Tool | Risk | Description |",
        "|------|------|-------------|",
    ]
    for name in sorted(by_name.keys()):
        entry = by_name[name]
        lines.append(
            f"| {entry.name} | {entry.risk} | {entry.description.strip()} |"
        )
    return "\n".join(lines)


def resolve_tool_entries(
    registry: ToolRegistry,
    bundle: CapabilityBundle,
) -> list[ToolEntry]:
    """Entries this worker may invoke (capability-local + main-shared tools)."""
    seen: set[str] = set()
    entries: list[ToolEntry] = []

    for entry in registry.resolve_for_capability(bundle.name):
        if entry.name in bundle.allowed_tools and entry.name not in seen:
            entries.append(entry)
            seen.add(entry.name)

    for tool_name in bundle.tools_executed_as_main:
        if tool_name not in bundle.allowed_tools or tool_name in seen:
            continue
        entry = registry.get(tool_name, "main")
        if entry is not None:
            entries.append(entry)
            seen.add(tool_name)

    return entries


def render_tool_cards_for_bundle(
    registry: ToolRegistry,
    bundle: CapabilityBundle,
) -> str:
    return render_tool_cards(resolve_tool_entries(registry, bundle))


def execution_capability(bundle: CapabilityBundle, tool_name: str) -> str:
    if tool_name in bundle.tools_executed_as_main:
        return "main"
    return bundle.name
