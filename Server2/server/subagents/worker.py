from __future__ import annotations

import asyncio
from typing import Any

from server.engine.pool import CompletionPriority, CompletionRequest, EnginePool
from server.engine.prompt import SubPromptContext, build_subagent_prompt
from server.logger import get_logger
from server.orchestrator.directives import DelegateDirective, parse_delegate_directives
from server.orchestrator.signal_bus import SignalBus
from server.orchestrator.tool_dispatch import run_subagent_tool_delegate
from server.subagents.capabilities import (
    CapabilityBundle,
    load_capability,
    render_tool_cards_for_bundle,
)
from server.subagents.report import ReportSignal, parse_report_directives, report
from server.tools.registry import ToolResult
from server.tools.runner import ToolRunner

log = get_logger("subagents.worker")

SUB_CAPABILITIES = frozenset({"research", "productivity", "comms", "data"})


class SubAgentWorker:
    """One ephemeral conversation per task_id; reports only — no transport."""

    def __init__(
        self,
        *,
        task_id: str,
        user_id: str,
        session_id: str,
        capability: str,
        goal: str,
        payload: dict[str, Any],
        engine_pool: EnginePool,
        tool_runner: ToolRunner,
        signal_bus: SignalBus,
        slot_id: int,
        warm_profile: str = "",
    ) -> None:
        self.task_id = task_id
        self.user_id = user_id
        self.session_id = session_id
        cap = capability.lower()
        if cap not in SUB_CAPABILITIES:
            raise ValueError(f"unsupported sub-agent capability: {capability}")
        self.capability = cap
        self.goal = goal
        self.payload = payload
        self.engine_pool = engine_pool
        self.tool_runner = tool_runner
        self.signal_bus = signal_bus
        self.slot_id = slot_id
        self.warm_profile = warm_profile
        self._bundle: CapabilityBundle = load_capability(cap)
        self._tool_cards = render_tool_cards_for_bundle(
            tool_runner.registry,
            self._bundle,
        )
        self._transcript: list[str] = []
        self._cancelled = False
        self._paused = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()

    def cancel(self) -> None:
        self._cancelled = True
        self._resume_event.set()

    async def pause(self, question: str, payload: dict[str, Any] | None = None) -> None:
        self._paused = True
        self._resume_event.clear()
        log.info(
            "subagent.paused",
            task_id=self.task_id,
            user_id=self.user_id,
            question=question[:120],
        )

    async def resume_with(self, message: str, *, mode: str = "reply") -> None:
        prefix = "User answer: " if mode == "reply" else "Additional context: "
        self._transcript.append(f"user: {prefix}{message.strip()}")
        self._paused = False
        self._resume_event.set()
        log.info("subagent.resume", task_id=self.task_id, mode=mode)

    async def run(self) -> None:
        max_steps = self._bundle.max_steps
        try:
            await self.signal_bus.publish_task_created(
                task_id=self.task_id,
                capability=self.capability,
                goal=self.goal,
                payload=self.payload,
            )
            if await self._run_seed_payload():
                return

            for step in range(max_steps):
                if self._cancelled:
                    await self.signal_bus.publish(
                        report(
                            self.task_id,
                            "ERROR",
                            "cancelled",
                            {"reason": "cancelled"},
                        )
                    )
                    return

                await self._resume_event.wait()
                if self._paused:
                    return

                raw = await self._model_step()
                if not raw.strip():
                    await self.signal_bus.publish(
                        report(self.task_id, "ERROR", "empty model output")
                    )
                    return

                self._transcript.append(f"assistant: {raw.strip()}")

                reports = parse_report_directives(raw, task_id=self.task_id)
                if not reports:
                    tool_block = await self._run_tool_delegates(raw)
                    if tool_block:
                        self._transcript.append(f"system: {tool_block}")
                    continue

                terminal = await self._handle_reports(reports)
                if terminal:
                    return

                tool_block = await self._run_tool_delegates(raw)
                if tool_block:
                    self._transcript.append(f"system: {tool_block}")

            await self.signal_bus.publish(
                report(
                    self.task_id,
                    "ERROR",
                    "step limit reached",
                    {"max_steps": max_steps},
                )
            )
        except asyncio.CancelledError:
            self._cancelled = True
            await self.signal_bus.publish(
                report(self.task_id, "ERROR", "cancelled", {"reason": "cancelled"})
            )
            raise
        except Exception as exc:
            log.exception("subagent.failed", task_id=self.task_id)
            await self.signal_bus.publish(
                report(
                    self.task_id,
                    "ERROR",
                    f"worker failed: {exc}",
                    {"retryable": True},
                )
            )
        finally:
            await self.engine_pool.free_slot(self.task_id)

    async def _run_seed_payload(self) -> bool:
        """
        Run the tool Main put in payload (e.g. deep_search) immediately.
        Returns True if the worker reached a terminal DONE/ERROR report.
        """
        tool_name = self.payload.get("tool")
        if not isinstance(tool_name, str) or tool_name not in self._bundle.allowed_tools:
            return False

        await self.signal_bus.publish(
            report(self.task_id, "STEP", f"Starting {tool_name} for this task")
        )

        async def _tool_progress(
            kind: str, _turn_id: str, summary: str
        ) -> None:
            if kind == "tool_started":
                await self.signal_bus.publish(
                    report(self.task_id, "STEP", summary[:160])
                )

        directive = DelegateDirective(
            capability=self.capability,
            goal=self.goal,
            payload=self.payload,
        )
        run = await run_subagent_tool_delegate(
            user_id=self.user_id,
            task_id=self.task_id,
            directive=directive,
            runner=self.tool_runner,
            on_event=_tool_progress,
        )
        if run.tool_name and run.result.summary:
            self._transcript.append(
                f"system: [TOOL_RESULT tool={run.tool_name}] {run.result.summary}"
            )

        if run.result.status != "ok":
            await self.signal_bus.publish(
                report(
                    self.task_id,
                    "ERROR",
                    run.result.summary or f"{tool_name} failed",
                    {"tool": tool_name},
                )
            )
            return True

        if tool_name == "deep_search":
            done_text = _summarize_deep_result(run.result)
            await self.signal_bus.publish(
                report(
                    self.task_id,
                    "DONE",
                    done_text[:2000],
                    {"tool": tool_name, "auto": True},
                )
            )
            return True

        return False

    async def _model_step(self) -> str:
        prompt = build_subagent_prompt(
            self._bundle,
            SubPromptContext(
                capability=self.capability,
                task_id=self.task_id,
                goal=self.goal,
                payload=self.payload,
                warm_profile=self.warm_profile,
                transcript_lines=self._transcript[-16:],
                tool_context=self._tool_cards,
            ),
        )
        request = CompletionRequest(prompt=prompt, max_tokens=768, temperature=0.5)
        handle = await self.engine_pool.submit_assigned(
            self.task_id,
            request,
            CompletionPriority.P1_SUBAGENT,
        )
        full = ""
        async for token in handle:
            full += token
        return full

    async def _run_tool_delegates(self, raw: str) -> str:
        directives = parse_delegate_directives(raw)
        if not directives:
            return ""
        parts: list[str] = []
        for directive in directives:
            if directive.capability.lower() != self.capability:
                continue
            tool_name = directive.payload.get("tool")
            if (
                isinstance(tool_name, str)
                and tool_name not in self._bundle.allowed_tools
            ):
                parts.append(
                    f"[TOOL_RESULT tool={tool_name} status=not_capable] "
                    f"Tool not in {self.capability} bundle"
                )
                continue
            run = await run_subagent_tool_delegate(
                user_id=self.user_id,
                task_id=self.task_id,
                directive=directive,
                runner=self.tool_runner,
            )
            if run.result.summary:
                parts.append(f"[TOOL_RESULT tool={run.tool_name}] {run.result.summary}")
        return "\n".join(parts)

    async def _handle_reports(self, reports: list[ReportSignal]) -> bool:
        terminal = False
        for sig in reports:
            row = await self.signal_bus.publish(sig)
            if sig.kind == "NEEDS_INFO":
                question = sig.payload.get("question")
                if not isinstance(question, str):
                    question = sig.summary
                await self.pause(str(question), sig.payload)
                terminal = True
            elif sig.kind in ("DONE", "ERROR"):
                terminal = True
            del row
        return terminal


def _summarize_deep_result(result: ToolResult) -> str:
    parts: list[str] = []
    if result.summary:
        parts.append(result.summary)
    articles = result.data.get("articles")
    if isinstance(articles, list):
        for article in articles[:3]:
            if not isinstance(article, dict):
                continue
            title = str(article.get("title", "")).strip()
            text = str(article.get("text", article.get("snippet", ""))).strip()
            if not text:
                continue
            if len(text) > 1200:
                text = text[:1200] + "…"
            if title:
                parts.append(f"{title}: {text}")
            else:
                parts.append(text)
    body = "\n\n".join(parts).strip()
    return body or "Deep search finished but returned little readable text."
