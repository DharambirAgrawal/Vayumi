from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from server.engine.pool import CompletionPriority, CompletionRequest, EnginePool
from server.engine.prompt import MainPromptContext, build_main_prompt
from server.logger import get_logger
from server.memory.session import (
    append_turn,
    compressed_history,
    load_or_create_session,
    recent_turns,
)
from server.memory.warm import build_warm_profile
from server.orchestrator.directives import (
    DelegateDirective,
    RecallDirective,
    RememberDirective,
    execute_directives,
    filter_profile_directives,
    format_recall_results,
    parse_answer_to_directives,
    parse_delegate_directives,
    parse_directives,
    parse_respond_via_override,
    parse_stop_task_directives,
    plan_acknowledgment,
    strip_directives,
)
from server.orchestrator.prose import finalize_assistant_prose, scrub_follow_up_prose
from server.orchestrator.signal_bus import SignalBus, TaskEventEmitter
from server.orchestrator.task_board import TaskBoard
from server.orchestrator.tool_dispatch import (
    DelegateRun,
    build_follow_up_context,
    format_subagent_spawn_block,
    run_delegate_directives,
    split_delegate_directives,
)
from server.orchestrator.plan_stream import PlanStreamHandler
from server.subagents.worker import SUB_CAPABILITIES, SubAgentWorker
from server.tools.runner import ToolEventEmitter, ToolRunner
from server.voice.respond_via import InputKind, RespondVia, apply_respond_via_override

log = get_logger("orchestrator.supervisor")

TurnKind = Literal["voice", "chat", "proactive", "system"]


def _history_for_tool_follow_up(history_lines: list[str]) -> list[str]:
    """Drop the assistant turn before the latest user message to avoid copy-paste answers."""
    if (
        len(history_lines) >= 2
        and history_lines[-1].startswith("user:")
        and history_lines[-2].startswith("assistant:")
    ):
        return [*history_lines[:-2], history_lines[-1]]
    return history_lines


@dataclass(frozen=True)
class TurnInput:
    kind: TurnKind
    text: str


@dataclass(frozen=True)
class TurnOutput:
    assistant_text: str
    raw_text: str
    turn_id: str
    respond_via: RespondVia


class Supervisor:
    def __init__(self, *, user_id: str, session_id: str) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self._ready = False
        self._persisted_session_id: str | None = None
        self.task_board = TaskBoard(user_id=user_id)
        self.signal_bus = SignalBus(user_id=user_id, task_board=self.task_board)
        self._workers: dict[str, SubAgentWorker] = {}
        self._worker_tasks: dict[str, asyncio.Task[None]] = {}

    async def ensure_session(self, client_meta: dict | None = None) -> None:
        sid = self.session_id
        if self._ready and self._persisted_session_id == sid:
            return
        await load_or_create_session(self.user_id, sid, client_meta)
        self._ready = True
        self._persisted_session_id = sid

    def attach_task_events(self, emitter: TaskEventEmitter | None) -> None:
        self.signal_bus.set_event_emitter(emitter)

    async def handle_turn(
        self,
        turn_input: TurnInput,
        *,
        engine_pool: EnginePool,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        computed_respond_via: RespondVia = "voice_and_chat",
        turn_id: str | None = None,
        tool_runner: ToolRunner | None = None,
        on_tool_event: ToolEventEmitter | None = None,
        on_task_event: TaskEventEmitter | None = None,
        on_status_caption: Callable[[str], Awaitable[None]] | None = None,
    ) -> TurnOutput:
        return await self.run_turn(
            turn_input.text,
            engine_pool=engine_pool,
            on_token=on_token,
            input_kind=turn_input.kind,
            computed_respond_via=computed_respond_via,
            turn_id=turn_id,
            tool_runner=tool_runner,
            on_tool_event=on_tool_event,
            on_task_event=on_task_event,
            on_status_caption=on_status_caption,
        )

    async def run_turn(
        self,
        user_text: str,
        *,
        engine_pool: EnginePool,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        input_kind: InputKind = "chat",
        computed_respond_via: RespondVia = "voice_and_chat",
        turn_id: str | None = None,
        tool_runner: ToolRunner | None = None,
        on_tool_event: ToolEventEmitter | None = None,
        on_task_event: TaskEventEmitter | None = None,
        on_status_caption: Callable[[str], Awaitable[None]] | None = None,
    ) -> TurnOutput:
        tid = turn_id or str(uuid.uuid4())
        await self.ensure_session()
        if on_task_event is not None:
            self.attach_task_events(on_task_event)

        user_text = user_text.strip()
        if not user_text:
            return TurnOutput(
                assistant_text="",
                raw_text="",
                turn_id=tid,
                respond_via=computed_respond_via,
            )

        warm = await build_warm_profile(self.user_id)
        history = await recent_turns(self.session_id, limit=8)
        summary = await compressed_history(self.session_id)
        await append_turn(self.session_id, self.user_id, "user", user_text)

        task_board_block = self.task_board.render_for_main()
        completed_inject = self.task_board.format_completed_injection(user_text)
        if completed_inject:
            task_board_block = (
                f"{task_board_block}\n\n{completed_inject}"
                if task_board_block
                else completed_inject
            )

        early_tool_tasks: list[asyncio.Task[list[DelegateRun]]] = []
        early_delegate_sigs: set[tuple] = set()

        def _delegate_sig(d: DelegateDirective) -> tuple:
            raw_args = d.payload.get("args", {})
            args = raw_args if isinstance(raw_args, dict) else {}
            tool = d.payload.get("tool")
            return (d.capability.lower(), tool, d.goal, json.dumps(args, sort_keys=True))

        def _split_delegates(
            delegate_directives: list[DelegateDirective],
        ) -> tuple[list[DelegateDirective], list[DelegateDirective]]:
            return split_delegate_directives(delegate_directives)

        async def _kick_early_tools(partial: str) -> None:
            if tool_runner is None:
                return
            main_batch, _ = _split_delegates(parse_delegate_directives(partial))
            pending = [
                d for d in main_batch if _delegate_sig(d) not in early_delegate_sigs
            ]
            if not pending:
                return
            for directive in pending:
                early_delegate_sigs.add(_delegate_sig(directive))
            ack_label = plan_acknowledgment(partial) or None

            async def _run_batch() -> list[DelegateRun]:
                return await run_delegate_directives(
                    user_id=self.user_id,
                    turn_id=tid,
                    directives=pending,
                    runner=tool_runner,
                    on_event=on_tool_event,
                    event_label_start=ack_label,
                )

            task = asyncio.create_task(
                _run_batch(),
                name=f"early-tools-{tid[:8]}-{len(early_tool_tasks)}",
            )
            early_tool_tasks.append(task)

        plan_handler: PlanStreamHandler | None = None
        plan_on_token = on_token
        if tool_runner is not None:
            plan_handler = PlanStreamHandler(
                on_status_caption=on_status_caption,
                on_delegates_ready=_kick_early_tools,
            )
            plan_on_token = plan_handler.on_token
        raw_text = await self._complete(
            user_text=user_text,
            warm_profile=warm,
            history=history,
            compressed_summary=summary,
            injected_context="",
            task_board_block=task_board_block,
            engine_pool=engine_pool,
            on_token=plan_on_token,
        )
        if plan_handler is not None:
            raw_text = await plan_handler.finalize()

        await self._apply_task_directives(
            raw_text,
            engine_pool=engine_pool,
            tool_runner=tool_runner,
        )

        profile_directives = filter_profile_directives(parse_directives(raw_text))
        recall_results = await execute_directives(self.user_id, profile_directives)

        main_directives, sub_directives = _split_delegates(
            parse_delegate_directives(raw_text)
        )

        spoken_ack = ""
        if plan_handler is not None:
            spoken_ack = plan_acknowledgment(raw_text)
            if (
                not plan_handler.ack_sent
                and on_status_caption is not None
                and spoken_ack
                and (main_directives or sub_directives)
            ):
                await on_status_caption(spoken_ack)

        spawn_blocks: list[str] = []

        async def _spawn_one(directive: DelegateDirective) -> str | None:
            cap = directive.capability.lower()
            if cap not in SUB_CAPABILITIES:
                return None
            existing = self.task_board.find_running(cap, directive.goal)
            if existing is not None:
                log.info(
                    "supervisor.spawn_skip_duplicate",
                    user_id=self.user_id,
                    task_id=existing.task_id,
                    goal=directive.goal[:80],
                )
                return format_subagent_spawn_block(
                    existing.task_id, cap, existing.goal
                )
            task_id = await self.spawn_subagent(
                cap,
                directive.goal,
                directive.payload,
                engine_pool=engine_pool,
                tool_runner=tool_runner,
                on_tool_event=on_tool_event,
            )
            return format_subagent_spawn_block(task_id, cap, directive.goal)

        remaining_main = [
            d for d in main_directives if _delegate_sig(d) not in early_delegate_sigs
        ]
        parallel_tasks: list[asyncio.Task[Any]] = []
        if sub_directives and tool_runner is not None:
            for directive in sub_directives:
                parallel_tasks.append(
                    asyncio.create_task(
                        _spawn_one(directive),
                        name=f"spawn-{tid[:8]}",
                    )
                )

        delegate_runs: list[DelegateRun] = []
        if remaining_main and tool_runner is not None:

            async def _run_remaining_main() -> list[DelegateRun]:
                return await run_delegate_directives(
                    user_id=self.user_id,
                    turn_id=tid,
                    directives=remaining_main,
                    runner=tool_runner,
                    on_event=on_tool_event,
                    event_label_start=spoken_ack or None,
                )

            parallel_tasks.append(
                asyncio.create_task(
                    _run_remaining_main(),
                    name=f"main-tools-{tid[:8]}",
                )
            )

        if early_tool_tasks:
            parallel_tasks.extend(early_tool_tasks)

        if parallel_tasks:
            results = await asyncio.gather(*parallel_tasks, return_exceptions=False)
            for result in results:
                if isinstance(result, list):
                    delegate_runs.extend(result)
                elif isinstance(result, str):
                    spawn_blocks.append(result)
        elif parse_delegate_directives(raw_text) and tool_runner is None:
            log.warning(
                "supervisor.delegates_skipped",
                user_id=self.user_id,
                count=len(parse_delegate_directives(raw_text)),
            )

        recalls = [d for d in profile_directives if isinstance(d, RecallDirective)]
        remembers = [d for d in profile_directives if isinstance(d, RememberDirective)]

        recall_block = (
            format_recall_results(recall_results)
            if recalls and recall_results
            else ""
        )
        injected_context = build_follow_up_context(
            recall_block=recall_block,
            spawn_blocks=spawn_blocks,
            delegate_runs=delegate_runs,
        )

        follow_up_text = ""
        if injected_context.strip():
            history = await recent_turns(self.session_id, limit=8)
            follow_up_text = await self._complete(
                user_text=user_text,
                warm_profile=warm,
                history=history,
                compressed_summary=summary,
                injected_context=injected_context,
                task_board_block=self.task_board.render_for_main(),
                engine_pool=engine_pool,
                on_token=on_token,
                allow_delegates=False,
            )
            raw_text = follow_up_text or raw_text

        answer_raw = follow_up_text or raw_text
        if injected_context.strip() and follow_up_text:
            answer_raw = scrub_follow_up_prose(
                follow_up_text, spoken_ack=spoken_ack
            )
        visible = finalize_assistant_prose(strip_directives(answer_raw))
        if not visible.strip():
            retry_context = ""
            if remembers:
                retry_context = "The user asked you to remember something. Confirm in one short spoken sentence."
            elif spawn_blocks:
                retry_context = (
                    "A background task was started (see SUBAGENT_SPAWN). "
                    "Tell the user in your own words — do not invent results yet."
                )
            elif delegate_runs:
                retry_context = (
                    "Tool results are above. Answer the user in plain spoken prose."
                )
            if retry_context:
                visible = finalize_assistant_prose(
                    strip_directives(
                        await self._complete(
                            user_text=user_text,
                            warm_profile=warm,
                            history=await recent_turns(self.session_id, limit=8),
                            compressed_summary=summary,
                            injected_context=retry_context,
                            task_board_block=self.task_board.render_for_main(),
                            engine_pool=engine_pool,
                            on_token=on_token,
                            allow_delegates=False,
                        )
                    )
                )

        override = parse_respond_via_override(follow_up_text or raw_text)
        respond_via = apply_respond_via_override(override, computed_respond_via)

        await append_turn(self.session_id, self.user_id, "assistant", visible)

        log.info(
            "supervisor.turn_complete",
            user_id=self.user_id,
            session_id=self.session_id,
            profile_directives=len(profile_directives),
            delegates=len(delegate_runs),
            spawns=len(spawn_blocks),
            respond_via=respond_via,
            input_kind=input_kind,
        )
        return TurnOutput(
            assistant_text=visible,
            raw_text=raw_text,
            turn_id=tid,
            respond_via=respond_via,
        )

    async def spawn_subagent(
        self,
        capability: str,
        goal: str,
        payload: dict[str, Any],
        *,
        engine_pool: EnginePool,
        tool_runner: ToolRunner,
        on_tool_event: ToolEventEmitter | None = None,
    ) -> str:
        cap = capability.lower()
        existing = self.task_board.find_running(cap, goal)
        if existing is not None:
            return existing.task_id
        task_id = str(uuid.uuid4())
        slot_id = await engine_pool.assign_slot(task_id, "subagent")
        warm = await build_warm_profile(self.user_id)
        worker = SubAgentWorker(
            task_id=task_id,
            user_id=self.user_id,
            session_id=self.session_id,
            capability=capability,
            goal=goal,
            payload=payload,
            engine_pool=engine_pool,
            tool_runner=tool_runner,
            signal_bus=self.signal_bus,
            slot_id=slot_id,
            warm_profile=warm,
        )
        self._workers[task_id] = worker

        async def _run() -> None:
            try:
                await worker.run()
            finally:
                self._workers.pop(task_id, None)
                self._worker_tasks.pop(task_id, None)

        self._worker_tasks[task_id] = asyncio.create_task(
            _run(),
            name=f"subagent-{task_id[:8]}",
        )
        log.info(
            "supervisor.spawn_subagent",
            user_id=self.user_id,
            task_id=task_id,
            capability=capability,
            slot_id=slot_id,
        )
        return task_id

    async def apply_answer_to_task(
        self,
        task_id: str,
        answer: str,
        mode: Literal["reply", "amendment"] = "reply",
        *,
        engine_pool: EnginePool,
        tool_runner: ToolRunner,
    ) -> bool:
        worker = self._workers.get(task_id)
        if worker is None:
            row = self.task_board.get(task_id)
            if row is None or row.status not in ("paused", "waiting_user"):
                log.warning("supervisor.answer_unknown_task", task_id=task_id)
                return False
            warm = await build_warm_profile(self.user_id)
            worker = SubAgentWorker(
                task_id=task_id,
                user_id=self.user_id,
                session_id=self.session_id,
                capability=row.capability,
                goal=row.goal,
                payload=row.payload,
                engine_pool=engine_pool,
                tool_runner=tool_runner,
                signal_bus=self.signal_bus,
                slot_id=await engine_pool.assign_slot(task_id, "subagent"),
                warm_profile=warm,
            )
            self._workers[task_id] = worker

        await worker.resume_with(answer, mode=mode)
        if task_id not in self._worker_tasks or self._worker_tasks[task_id].done():

            async def _run() -> None:
                try:
                    await worker.run()
                finally:
                    self._workers.pop(task_id, None)
                    self._worker_tasks.pop(task_id, None)

            self._worker_tasks[task_id] = asyncio.create_task(
                _run(),
                name=f"subagent-resume-{task_id[:8]}",
            )
        row = self.task_board.get(task_id)
        if row is not None and row.status == "paused":
            row.status = "running"
            row.waiting_for = None
        return True

    async def cancel_task(self, task_id: str, *, engine_pool: EnginePool) -> bool:
        worker = self._workers.pop(task_id, None)
        task = self._worker_tasks.pop(task_id, None)
        if task is not None and not task.done():
            if worker is not None:
                worker.cancel()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await engine_pool.free_slot(task_id)
        row = self.task_board.mark_cancelled(task_id)
        if self.signal_bus._on_event is not None:
            await self.signal_bus._on_event("task_done", task_id, "cancelled")
        return row is not None or task is not None

    async def _apply_task_directives(
        self,
        text: str,
        *,
        engine_pool: EnginePool,
        tool_runner: ToolRunner | None,
    ) -> None:
        for directive in parse_stop_task_directives(text):
            await self.cancel_task(directive.task_id, engine_pool=engine_pool)
        if tool_runner is None:
            return
        for directive in parse_answer_to_directives(text):
            await self.apply_answer_to_task(
                directive.task_id,
                directive.answer,
                directive.mode,
                engine_pool=engine_pool,
                tool_runner=tool_runner,
            )

    async def _complete(
        self,
        *,
        user_text: str,
        warm_profile: str,
        history: list,
        compressed_summary: str,
        injected_context: str,
        task_board_block: str,
        engine_pool: EnginePool,
        on_token: Callable[[str], Awaitable[None]] | None,
        allow_delegates: bool = True,
    ) -> str:
        history_lines = [f"{turn.role}: {turn.text}" for turn in history]
        if injected_context.strip() and "[TOOL_RESULT" in injected_context:
            history_lines = _history_for_tool_follow_up(history_lines)
        context = injected_context
        if not allow_delegates and context:
            context = (
                f"{context}\n\nDo not emit [DELEGATE], [REMEMBER], or [RECALL] in this reply."
            )
        prompt = build_main_prompt(
            MainPromptContext(
                user_text=user_text,
                warm_profile=warm_profile,
                history_lines=history_lines,
                compressed_summary=compressed_summary,
                recall_context=context,
                task_board_block=task_board_block,
            )
        )
        request = CompletionRequest(
            prompt=prompt,
            stop=("\n\n```", "\n```\n"),
            max_tokens=300 if not allow_delegates else 512,
            cache_prompt=True if not allow_delegates else False,
        )
        handle = await engine_pool.submit(request, CompletionPriority.P0_MAIN, slot_hint=0)

        full_text = ""
        async for token in handle:
            full_text += token
            if on_token is not None:
                await on_token(token)
        return full_text
