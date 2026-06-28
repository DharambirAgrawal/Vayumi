from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from server.logger import get_logger
from server.orchestrator.directives import DelegateDirective
from server.subagents.capabilities import execution_capability, load_capability
from server.engine.pool import ParsedToolCall
from server.tools.registry import ToolCall, ToolResult
from server.tools.runner import ToolEventEmitter, ToolRunner

log = get_logger("orchestrator.tool_dispatch")

MAX_DELEGATES_PER_TURN = 6
MAIN_TOOLS = frozenset({"tool_search", "web_search", "memory_save", "memory_recall"})
SUB_CAPABILITIES = frozenset({"research", "productivity", "comms", "data"})


@dataclass(frozen=True)
class DelegateRun:
    """A capability tool executed inside a sub-agent worker."""

    directive: DelegateDirective
    result: ToolResult
    tool_name: str | None = None


# ── Main-agent native tool-call loop ────────────────────────────────────────


@dataclass(frozen=True)
class ToolCallRun:
    """One executed native tool call, keeping the call id for the round-trip."""

    call: ParsedToolCall
    result: ToolResult


async def run_main_tool_calls(
    *,
    user_id: str,
    turn_id: str,
    tool_calls: list[ParsedToolCall],
    runner: ToolRunner,
    on_event: ToolEventEmitter | None = None,
    event_label_start: str | None = None,
) -> list[ToolCallRun]:
    """Execute the main agent's tool calls (e.g. web_search from a [SEARCH]
    directive), preserving each call id and result for grounding the answer."""
    runs: list[ToolCallRun] = []
    for index, call in enumerate(tool_calls[:MAX_DELEGATES_PER_TURN]):
        try:
            raw_args = json.loads(call.arguments)
        except json.JSONDecodeError:
            raw_args = {}
        if not isinstance(raw_args, dict):
            raw_args = {}

        if call.name not in MAIN_TOOLS:
            result = ToolResult(
                status="not_capable",
                summary=f"{call.name} is not available to the main agent.",
            )
        else:
            label = event_label_start if index == 0 else None
            result = await runner.execute(
                turn_id,
                ToolCall(name=call.name, args=raw_args, capability="main"),
                user_id=user_id,
                on_event=on_event,
                event_label_start=label,
            )
        runs.append(ToolCallRun(call=call, result=result))
    return runs


# ── Directive helpers (sub-agent delegation + recall/spawn follow-up) ────────


def build_follow_up_context(
    *,
    recall_block: str = "",
    spawn_blocks: list[str] | None = None,
) -> str:
    """Context for the clean second pass after a recall and/or sub-agent spawn.

    This never carries tool snippets — the main native tool loop grounds those
    via role:tool messages. It only injects recalled facts and a note that
    background work has started.
    """
    spawn_blocks = spawn_blocks or []
    parts: list[str] = []
    if recall_block.strip():
        parts.append(recall_block.strip())
    if spawn_blocks:
        parts.append("=== Background (still running — do not invent their results) ===")
        parts.extend(spawn_blocks)

    today = date.today().isoformat()
    if spawn_blocks and recall_block.strip():
        parts.append(
            f"Today is {today}. Answer using the recalled facts above, and add ONE "
            "short sentence that the background task has started — do not promise to "
            "notify later (the server pushes results when done). No [DELEGATE]."
        )
    elif spawn_blocks:
        parts.append(
            f"Today is {today}. Tell the user briefly that you started the background "
            "task and they'll hear the result when it's done. 1–2 sentences. No [DELEGATE]."
        )
    elif recall_block.strip():
        parts.append(
            f"Today is {today}. Answer the user using the recalled facts above, in "
            "plain spoken prose. No [DELEGATE]."
        )
    return "\n\n".join(parts)


def split_delegate_directives(
    directives: list[DelegateDirective],
) -> tuple[list[DelegateDirective], list[DelegateDirective]]:
    main: list[DelegateDirective] = []
    subagent: list[DelegateDirective] = []
    for directive in directives:
        cap = directive.capability.lower()
        if cap == "main":
            main.append(directive)
        elif cap in SUB_CAPABILITIES:
            subagent.append(directive)
    return main, subagent


def format_subagent_spawn_block(task_id: str, capability: str, goal: str) -> str:
    cap = capability.lower()
    if cap == "research":
        label = "research"
    elif cap == "productivity":
        label = "productivity task"
    elif cap == "comms":
        label = "communications task"
    else:
        label = "background task"
    return f"Background {label} started for: {goal}. Results will arrive when done."


async def run_subagent_tool_delegate(
    *,
    user_id: str,
    task_id: str,
    directive: DelegateDirective,
    runner: ToolRunner,
    on_event: ToolEventEmitter | None = None,
    event_label_start: str | None = None,
) -> DelegateRun:
    """Execute a sub-agent capability tool via ToolRunner (bundle-gated)."""
    capability = directive.capability.lower()
    try:
        bundle = load_capability(capability)
    except ValueError:
        return DelegateRun(
            directive=directive,
            tool_name=None,
            result=ToolResult(
                status="not_capable",
                summary=f"Unknown capability {capability}",
            ),
        )

    tool_name = directive.payload.get("tool")
    if not isinstance(tool_name, str) or tool_name not in bundle.allowed_tools:
        return DelegateRun(
            directive=directive,
            tool_name=None,
            result=ToolResult(
                status="not_capable",
                summary=f"Tool {tool_name!r} is not in the {capability} capability bundle",
            ),
        )

    raw_args = directive.payload.get("args", {})
    if not isinstance(raw_args, dict):
        raw_args = {}

    exec_capability = execution_capability(bundle, tool_name)
    tool_call = ToolCall(
        name=tool_name,
        args=raw_args,
        capability=exec_capability,  # type: ignore[arg-type]
    )
    result = await runner.execute(
        task_id,
        tool_call,
        user_id=user_id,
        on_event=on_event,
        event_label_start=event_label_start,
    )
    return DelegateRun(directive=directive, tool_name=tool_name, result=result)
