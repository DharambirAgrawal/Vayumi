from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date

from server.logger import get_logger
from server.orchestrator.directives import DelegateDirective
from server.subagents.capabilities import execution_capability, load_capability
from server.tools.registry import ToolCall, ToolResult, render_tool_result_for_prompt
from server.tools.runner import ToolEventEmitter, ToolRunner

log = get_logger("orchestrator.tool_dispatch")

MAX_DELEGATES_PER_TURN = 6
MAIN_TOOLS = frozenset({"tool_search", "web_search", "memory_save", "memory_recall"})
SUB_CAPABILITIES = frozenset({"research", "productivity", "comms", "data"})


@dataclass(frozen=True)
class DelegateRun:
    directive: DelegateDirective
    result: ToolResult
    tool_name: str | None = None


async def run_delegate_directives(
    *,
    user_id: str,
    turn_id: str,
    directives: list[DelegateDirective],
    runner: ToolRunner,
    on_event: ToolEventEmitter | None = None,
    event_label_start: str | None = None,
) -> list[DelegateRun]:
    """Execute DELEGATE directives for this turn (main tools only in Step 7)."""
    batch = directives[:MAX_DELEGATES_PER_TURN]
    if len(directives) > MAX_DELEGATES_PER_TURN:
        log.warning(
            "tool_dispatch.truncated",
            user_id=user_id,
            turn_id=turn_id,
            requested=len(directives),
            limit=MAX_DELEGATES_PER_TURN,
        )

    if not batch:
        return []

    tasks: list[asyncio.Task[tuple[int, DelegateRun]]] = []
    for index, directive in enumerate(batch):
        label = event_label_start if index == 0 else None

        async def _run_one(
            idx: int, item: DelegateDirective, start_label: str | None
        ) -> tuple[int, DelegateRun]:
            result = await _run_one_delegate(
                user_id=user_id,
                turn_id=turn_id,
                directive=item,
                runner=runner,
                on_event=on_event,
                event_label_start=start_label,
            )
            return idx, result

        tasks.append(
            asyncio.create_task(
                _run_one(index, directive, label),
                name=f"main-tool-{turn_id[:8]}-{index}",
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=False)
    results.sort(key=lambda item: item[0])
    return [item[1] for item in results]


async def _run_one_delegate(
    *,
    user_id: str,
    turn_id: str,
    directive: DelegateDirective,
    runner: ToolRunner,
    on_event: ToolEventEmitter | None,
    event_label_start: str | None = None,
) -> DelegateRun:
    capability = directive.capability.lower()

    if capability != "main":
        return DelegateRun(
            directive=directive,
            tool_name=None,
            result=ToolResult(
                status="not_capable",
                summary=(
                    f"Capability {directive.capability} is not available yet "
                    "(sub-agents ship in a later step)"
                ),
            ),
        )

    tool_name = directive.payload.get("tool")
    if not isinstance(tool_name, str) or tool_name not in MAIN_TOOLS:
        return DelegateRun(
            directive=directive,
            tool_name=None,
            result=ToolResult(
                status="error",
                summary="Invalid main tool payload: expected tool in MAIN_TOOLS",
                data={"payload": directive.payload},
            ),
        )

    raw_args = directive.payload.get("args", {})
    if not isinstance(raw_args, dict):
        raw_args = {}

    tool_call = ToolCall(
        name=tool_name,
        args=raw_args,
        capability="main",
    )
    result = await runner.execute(
        turn_id,
        tool_call,
        user_id=user_id,
        on_event=on_event,
        event_label_start=event_label_start,
    )
    return DelegateRun(directive=directive, tool_name=tool_name, result=result)


def format_delegate_results(runs: list[DelegateRun]) -> str:
    if not runs:
        return ""
    lines: list[str] = []
    for index, run in enumerate(runs, start=1):
        goal = run.directive.goal.strip() or f"part {index}"
        lines.append(f"--- Immediate result {index}: {goal} ---")
        name = run.tool_name or run.directive.capability
        lines.append(render_tool_result_for_prompt(name, run.result))
    return "\n".join(lines)


def build_follow_up_context(
    *,
    recall_block: str = "",
    spawn_blocks: list[str],
    delegate_runs: list[DelegateRun],
) -> str:
    """Merge quick tool results + background spawns for a multi-part user request."""
    parts: list[str] = []
    if recall_block.strip():
        parts.append(recall_block.strip())

    if delegate_runs:
        parts.append("=== Answer now (immediate tool results) ===")
        parts.append(format_delegate_results(delegate_runs))

    if spawn_blocks:
        parts.append("=== Background (still running — do not invent their results) ===")
        parts.extend(spawn_blocks)

    today = date.today().isoformat()
    if delegate_runs and spawn_blocks:
        parts.append(
            f"Today is {today}. The user asked for multiple things. Cover every immediate "
            "result section above (e.g. weather) in your own words. Add only ONE short "
            "sentence that deep research has started — do NOT say you are still working, "
            "do NOT promise to notify later (the server pushes results when done). "
            "Do not repeat your plan opening line. No [DELEGATE]."
        )
    elif len(delegate_runs) > 1:
        parts.append(
            f"Today is {today}. The user asked for multiple topics — address each immediate "
            "result section. Snippets only; do not invent prices or dates. No [DELEGATE]."
        )
    elif delegate_runs:
        parts.append(
            f"Today is {today}. Answer from the immediate results only — casual, 2–4 "
            "sentences. Snippet numbers are source of truth. No [DELEGATE]."
        )
    elif spawn_blocks:
        parts.append(
            "Background research is running. Tell the user briefly that you started it and "
            "they will hear the full summary when it finishes — do not promise vague "
            "\"I'll use more resources\" without a DELEGATE. Keep it to 1–2 sentences. "
            "No [DELEGATE]."
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
    return (
        f"Background research started for: {goal}. Results will arrive when done."
    )


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


def compact_delegate_summary(runs: list[DelegateRun]) -> str:
    parts = []
    for run in runs:
        label = run.tool_name or run.directive.capability
        parts.append(f"{label}:{run.result.status}")
    return "; ".join(parts)
