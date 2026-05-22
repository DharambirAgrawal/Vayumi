from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from server.logger import get_logger
from server.tools.registry import ToolCall, ToolRegistry, ToolResult, validate_tool_args

log = get_logger("tools.runner")

ToolEventKind = Literal["tool_started", "tool_done"]
ToolEventEmitter = Callable[[ToolEventKind, str, str], Awaitable[None]]


class ToolRunner:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    async def execute(
        self,
        task_id: str,
        tool_call: ToolCall,
        *,
        user_id: str,
        on_event: ToolEventEmitter | None = None,
    ) -> ToolResult:
        entry = self._registry.get(tool_call.name)
        if entry is None:
            return ToolResult(
                status="error",
                summary=f"Unknown tool: {tool_call.name}",
                retryable=False,
            )

        if entry.capability != tool_call.capability:
            return ToolResult(
                status="not_capable",
                summary=(
                    f"Tool {tool_call.name} belongs to capability "
                    f"{entry.capability}, not {tool_call.capability}"
                ),
            )

        arg_error = validate_tool_args(entry.args_schema, tool_call.args)
        if arg_error:
            return ToolResult(status="error", summary=arg_error, retryable=False)

        if entry.requires_confirmation and not tool_call.args.get("confirmed"):
            return require_confirmation(
                tool_call,
                preview={"tool": tool_call.name, "args": tool_call.args},
            )

        if entry.requires_confirmation and tool_call.args.get("confirmed"):
            conf_id = tool_call.args.get("confirmation_id")
            if not isinstance(conf_id, str) or not verify_confirmation(
                conf_id, tool_call
            ):
                return ToolResult(
                    status="error",
                    summary="Invalid or expired confirmation",
                    retryable=False,
                )

        started_summary = f"{tool_call.name} started"
        if on_event is not None:
            await on_event("tool_started", task_id, started_summary)

        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                entry.fn(user_id=user_id, **tool_call.args),
                timeout=entry.timeout_s,
            )
            if not isinstance(result, ToolResult):
                result = ToolResult(
                    status="error",
                    summary=f"Tool {tool_call.name} returned invalid result",
                )
        except TimeoutError:
            result = ToolResult(
                status="error",
                summary=f"Tool {tool_call.name} timed out after {entry.timeout_s}s",
                retryable=True,
            )
        except Exception as exc:
            log.exception(
                "tools.execute_failed",
                tool=tool_call.name,
                user_id=user_id,
                task_id=task_id,
            )
            result = ToolResult(
                status="error",
                summary=f"Tool {tool_call.name} failed: {exc}",
                retryable=True,
            )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        done_summary = f"{tool_call.name} {result.status} ({elapsed_ms}ms)"
        if on_event is not None:
            await on_event("tool_done", task_id, done_summary)

        log.info(
            "tools.execute_complete",
            tool=tool_call.name,
            user_id=user_id,
            task_id=task_id,
            status=result.status,
            latency_ms=elapsed_ms,
        )
        return result


def require_confirmation(
    tool_call: ToolCall,
    *,
    preview: dict[str, Any],
) -> ToolResult:
    confirmation_id = f"confirm_{uuid.uuid4().hex[:12]}"
    payload = json.dumps(
        {"tool": tool_call.name, "args": tool_call.args},
        sort_keys=True,
        ensure_ascii=False,
    )
    action_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return ToolResult(
        status="confirmation_required",
        summary=f"Confirm {tool_call.name}?",
        confirmation={
            "id": confirmation_id,
            "action": tool_call.name,
            "preview": preview,
            "hash": action_hash,
        },
        safe_to_show_user=True,
    )


def verify_confirmation(confirmation_id: str, tool_call: ToolCall) -> bool:
    if not confirmation_id.startswith("confirm_"):
        return False
    if not tool_call.args.get("confirmed"):
        return False
    return isinstance(tool_call.args.get("confirmation_id"), str)
