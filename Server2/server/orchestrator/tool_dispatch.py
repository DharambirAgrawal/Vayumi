from __future__ import annotations

import asyncio
from dataclasses import dataclass

from server.logger import get_logger
from server.orchestrator.directives import DelegateDirective
from server.orchestrator.tool_intent import suggest_web_search_query
from server.tools.registry import ToolCall, ToolResult, render_tool_result_for_prompt
from server.tools.runner import ToolEventEmitter, ToolRunner

log = get_logger("orchestrator.tool_dispatch")

MAX_DELEGATES_PER_TURN = 6
MAIN_TOOLS = frozenset({"tool_search", "web_search", "memory_save", "memory_recall"})


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

    tasks = [
        _run_one_delegate(
            user_id=user_id,
            turn_id=turn_id,
            directive=directive,
            runner=runner,
            on_event=on_event,
        )
        for directive in batch
    ]
    return list(await asyncio.gather(*tasks))


async def _run_one_delegate(
    *,
    user_id: str,
    turn_id: str,
    directive: DelegateDirective,
    runner: ToolRunner,
    on_event: ToolEventEmitter | None,
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
    )
    return DelegateRun(directive=directive, tool_name=tool_name, result=result)


def format_delegate_results(runs: list[DelegateRun]) -> str:
    if not runs:
        return ""
    lines = []
    for run in runs:
        name = run.tool_name or run.directive.capability
        lines.append(render_tool_result_for_prompt(name, run.result))
        if run.directive.goal:
            lines.append(f"(goal: {run.directive.goal})")
    block = "\n".join(lines)
    hint = (
        "Answer the user's latest message using the tool results above. "
        "Summarize in plain prose only — never paste [TOOL_RESULT] lines or "
        "'Found N tool(s)' metadata. If results are empty, say so; do not invent news. "
        "Do not emit another [DELEGATE] block in this reply."
    )
    return f"{block}\n\n{hint}"


def coerce_delegates_for_live_web(
    user_text: str,
    directives: list[DelegateDirective],
) -> list[DelegateDirective]:
    """
    News/stock/live queries must run web_search, not tool_search alone.
    tool_search only lists tool names — it does not fetch headlines.
    """
    query = suggest_web_search_query(user_text)
    if not query:
        return directives

    web = DelegateDirective(
        capability="main",
        goal="fetch live web results",
        payload={
            "tool": "web_search",
            "args": {"query": query, "max_results": 8, "search_depth": "basic"},
        },
    )

    if not directives:
        return [web]

    tools = [
        d.payload.get("tool")
        for d in directives
        if isinstance(d.payload.get("tool"), str)
    ]
    if "web_search" in tools:
        return directives

    if tools == ["tool_search"] or set(tools) <= {"tool_search"}:
        log.info("tool_dispatch.coerce_web_search", reason="tool_search_only")
        return [web]

    return [web, *directives]


def web_search_succeeded(runs: list[DelegateRun]) -> bool:
    for run in runs:
        if run.tool_name == "web_search" and run.result.status == "ok":
            data = run.result.data.get("results", [])
            if isinstance(data, list) and len(data) > 0:
                return True
    return False


def tool_status_message(
    user_text: str,
    directives: list[DelegateDirective],
) -> str:
    """Short user-facing line while tools run (PLAN: announce before execute)."""
    for directive in directives:
        tool = directive.payload.get("tool")
        if tool == "web_search":
            args = directive.payload.get("args", {})
            query = user_text
            if isinstance(args, dict) and isinstance(args.get("query"), str):
                query = args["query"]
            short = query.strip()[:72]
            if len(query.strip()) > 72:
                short += "…"
            return f"Searching the web for {short}…"
        if tool == "memory_recall":
            return "Checking what I remember…"
        if tool == "memory_save":
            return "Saving that to memory…"
        if tool == "tool_search":
            return "Checking which tools I can use…"
    return "Working on that…"


def compact_delegate_summary(runs: list[DelegateRun]) -> str:
    parts = []
    for run in runs:
        label = run.tool_name or run.directive.capability
        parts.append(f"{label}:{run.result.status}")
    return "; ".join(parts)
