from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from server.engine.pool import (
    ChatCompletionResult,
    CompletionPriority,
    CompletionRequest,
    EnginePool,
)
from server.engine.prompt import (
    MainPromptContext,
    build_main_chat_messages,
)
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
    contains_directive_leak,
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
from server.orchestrator.prose import (
    finalize_assistant_prose,
    sanitize_spoken_prose,
    scrub_follow_up_prose,
)
from server.orchestrator.tool_fallback import (
    fallback_web_search_query,
    is_insufficient_tool_answer,
    is_web_search_only_runs,
    needs_web_search_synthesis,
    should_fallback_web_search,
    tool_status_while_searching,
)
from server.orchestrator.signal_bus import SignalBus, TaskEventEmitter
from server.orchestrator.task_board import TaskBoard
from server.orchestrator.tool_dispatch import (
    DelegateRun,
    build_follow_up_context,
    format_subagent_spawn_block,
    run_delegate_directives,
    run_native_tool_calls,
    speak_web_search_results,
    split_delegate_directives,
)
from server.tools.openai_schema import openai_tools_for_main
from server.engine.pool import ParsedToolCall
from server.subagents.worker import SUB_CAPABILITIES, SubAgentWorker
from server.tools.runner import ToolEventEmitter, ToolRunner
from server.voice.respond_via import InputKind, RespondVia, apply_respond_via_override

log = get_logger("orchestrator.supervisor")

TurnKind = Literal["voice", "chat", "proactive", "system"]
CompletionMode = Literal["plan", "answer", "retry"]

_EMPTY_ASSISTANT_FALLBACK = (
    "Sorry, I blanked for a second — could you say that again?"
)

_MAX_TOKENS_BY_MODE: dict[CompletionMode, int] = {
    "plan": 384,
    "answer": 1024,
    "retry": 512,
}


def _max_tokens_for_mode(mode: CompletionMode) -> int:
    return _MAX_TOKENS_BY_MODE[mode]


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
    revoice_final: bool = False


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
        self._pending_task_answers: dict[str, tuple[str, Literal["reply", "amendment"]]] = {}

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
        allow_delegates: bool | None = None,
        injected_context: str = "",
    ) -> TurnOutput:
        proactive = turn_input.kind == "proactive"
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
            allow_delegates=False if proactive else allow_delegates,
            injected_context=injected_context,
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
        allow_delegates: bool | None = None,
        injected_context: str = "",
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

        delegates_allowed = True if allow_delegates is None else allow_delegates

        warm = await build_warm_profile(self.user_id)
        history = await recent_turns(self.session_id, limit=8)
        summary = await compressed_history(self.session_id)
        await append_turn(self.session_id, self.user_id, "user", user_text)

        task_board_block = self.task_board.render_for_main()
        if delegates_allowed:
            completed_inject = self.task_board.format_completed_injection(user_text)
            if completed_inject:
                task_board_block = (
                    f"{task_board_block}\n\n{completed_inject}"
                    if task_board_block
                    else completed_inject
                )

        if not delegates_allowed:
            raw_text = await self._complete(
                user_text=user_text,
                warm_profile=warm,
                history=history,
                compressed_summary=summary,
                injected_context=injected_context,
                task_board_block=task_board_block,
                engine_pool=engine_pool,
                on_token=on_token,
                allow_delegates=False,
                completion_mode="answer",
            )
            override = parse_respond_via_override(raw_text)
            respond_via = apply_respond_via_override(override, computed_respond_via)
            visible = finalize_assistant_prose(strip_directives(raw_text))
            visible = self._ensure_visible_reply(visible)
            if visible.strip():
                await append_turn(self.session_id, self.user_id, "assistant", visible)
            log.info(
                "supervisor.turn_complete",
                user_id=self.user_id,
                session_id=self.session_id,
                respond_via=respond_via,
                input_kind=input_kind,
                proactive=input_kind == "proactive",
            )
            return TurnOutput(
                assistant_text=visible,
                raw_text=raw_text,
                turn_id=tid,
                respond_via=respond_via,
            )

        messages = self._build_main_messages(
            user_text=user_text,
            warm_profile=warm,
            history=history,
            compressed_summary=summary,
            injected_context=injected_context,
            task_board_block=task_board_block,
        )

        first: ChatCompletionResult
        if tool_runner is not None:
            first = await engine_pool.complete_chat(
                CompletionRequest(
                    prompt=messages,
                    tools=openai_tools_for_main(tool_runner.registry),
                    max_tokens=_max_tokens_for_mode("answer"),
                    cache_prompt=True,
                    stream=False,
                    temperature=0.7,
                    stop=("```", "[TOOL_RESULT", "[SUBAGENT_SPAWN"),
                ),
            )
            log.info(
                "supervisor.tool_pass",
                user_id=self.user_id,
                session_id=self.session_id,
                tool_calls=len(first.tool_calls),
                finish_reason=first.finish_reason,
                content_chars=len(first.content or ""),
            )
        else:
            text = await self._complete(
                user_text=user_text,
                warm_profile=warm,
                history=history,
                compressed_summary=summary,
                injected_context=injected_context,
                task_board_block=task_board_block,
                engine_pool=engine_pool,
                on_token=on_token,
                completion_mode="answer",
            )
            first = ChatCompletionResult(content=text, tool_calls=[])

        spawn_blocks: list[str] = []
        remembers: list[RememberDirective] = []
        profile_directives: list = []
        raw_text = first.content
        spoken_ack = plan_acknowledgment(raw_text) or (
            raw_text.strip() if raw_text else ""
        )
        delegate_runs: list[DelegateRun] = []
        follow_up_text = ""
        revoice_final = False
        tool_wait_line = tool_status_while_searching(raw_text)

        if first.tool_calls and tool_runner is not None:
            if tool_wait_line and on_status_caption is not None:
                await on_status_caption(tool_wait_line)

            delegate_runs = await run_native_tool_calls(
                user_id=self.user_id,
                turn_id=tid,
                tool_calls=first.tool_calls,
                runner=tool_runner,
                on_event=on_tool_event,
                event_label_start=tool_wait_line or None,
            )
            follow_up_text, revoice_final = await self._answer_after_web_search(
                user_text=user_text,
                warm_profile=warm,
                history=history,
                compressed_summary=summary,
                task_board_block=self.task_board.render_for_main(),
                spoken_ack=tool_wait_line,
                delegate_runs=delegate_runs,
                engine_pool=engine_pool,
                on_token=on_token,
            )
            raw_text = follow_up_text or raw_text
        else:
            await self._apply_task_directives(
                raw_text,
                engine_pool=engine_pool,
                tool_runner=tool_runner,
            )

            profile_directives = filter_profile_directives(
                parse_directives(raw_text)
            )
            recall_results = await execute_directives(self.user_id, profile_directives)

            main_directives, sub_directives = split_delegate_directives(
                parse_delegate_directives(raw_text)
            )

            if (
                not main_directives
                and tool_runner is not None
                and should_fallback_web_search(model_content=raw_text)
            ):
                log.warning(
                    "supervisor.web_search_fallback",
                    user_id=self.user_id,
                    session_id=self.session_id,
                    user_text=user_text[:120],
                )
                search_query = fallback_web_search_query(
                    user_text=user_text,
                    model_content=raw_text,
                )
                fallback_call = ParsedToolCall(
                    id="call_fallback_web_search",
                    name="web_search",
                    arguments=json.dumps(
                        {"query": search_query, "max_results": 8},
                        ensure_ascii=False,
                    ),
                )
                if tool_wait_line and on_status_caption is not None:
                    await on_status_caption(tool_wait_line)
                delegate_runs = await run_native_tool_calls(
                    user_id=self.user_id,
                    turn_id=tid,
                    tool_calls=[fallback_call],
                    runner=tool_runner,
                    on_event=on_tool_event,
                    event_label_start=tool_wait_line or None,
                )
                follow_up_text, revoice_final = await self._answer_after_web_search(
                    user_text=user_text,
                    warm_profile=warm,
                    history=history,
                    compressed_summary=summary,
                    task_board_block=self.task_board.render_for_main(),
                    spoken_ack=tool_wait_line,
                    delegate_runs=delegate_runs,
                    engine_pool=engine_pool,
                    on_token=on_token,
                )
                raw_text = follow_up_text or raw_text
                main_directives = []
            elif (
                on_status_caption is not None
                and spoken_ack
                and (main_directives or sub_directives)
            ):
                await on_status_caption(spoken_ack)

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

            parallel_tasks: list[asyncio.Task[Any]] = []
            if sub_directives and tool_runner is not None:
                for directive in sub_directives:
                    parallel_tasks.append(
                        asyncio.create_task(
                            _spawn_one(directive),
                            name=f"spawn-{tid[:8]}",
                        )
                    )

            if main_directives and tool_runner is not None:

                async def _run_remaining_main() -> list[DelegateRun]:
                    return await run_delegate_directives(
                        user_id=self.user_id,
                        turn_id=tid,
                        directives=main_directives,
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

            recalls = [
                d for d in profile_directives if isinstance(d, RecallDirective)
            ]
            remembers = [
                d for d in profile_directives if isinstance(d, RememberDirective)
            ]

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

            if injected_context.strip() and is_insufficient_tool_answer(
                follow_up_text
            ):
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
                    completion_mode="answer",
                )
                raw_text = follow_up_text or raw_text

        if follow_up_text and spoken_ack:
            scrubbed = scrub_follow_up_prose(
                follow_up_text, spoken_ack=spoken_ack
            )
            answer_raw = scrubbed if scrubbed.strip() else follow_up_text
        else:
            answer_raw = follow_up_text or raw_text
        visible = finalize_assistant_prose(strip_directives(answer_raw))
        if contains_directive_leak(visible):
            visible = ""
        visible, delegate_runs, grounded_revoice = await self._ground_lookup_answer(
            user_text=user_text,
            visible=visible,
            delegate_runs=delegate_runs,
            tool_runner=tool_runner,
            turn_id=tid,
            on_tool_event=on_tool_event,
        )
        if grounded_revoice and on_token is not None:
            revoice_final = True
        if not visible.strip():
            retry_context = ""
            if remembers:
                retry_context = (
                    "The user asked you to remember something. "
                    "Confirm in one short spoken sentence."
                )
            elif spawn_blocks:
                retry_context = (
                    "A background task was started. "
                    "Tell the user in your own words — do not invent results yet."
                )
            elif delegate_runs:
                synthesized = speak_web_search_results(delegate_runs)
                if synthesized:
                    visible = sanitize_spoken_prose(synthesized)
                    retry_context = ""
                else:
                    injected = build_follow_up_context(
                        recall_block="",
                        spawn_blocks=[],
                        delegate_runs=delegate_runs,
                    )
                    retry_context = (
                        f"{injected}\n\nGive a short spoken answer with real numbers "
                        "or facts from the snippets above."
                        if injected.strip()
                        else "Tool results are above. Answer in plain spoken prose."
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
                            completion_mode="retry",
                        )
                    )
                )
        override = parse_respond_via_override(follow_up_text or raw_text)
        respond_via = apply_respond_via_override(override, computed_respond_via)

        visible = self._ensure_visible_reply(visible)
        if visible.strip():
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
            revoice_final=revoice_final,
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
        await self.signal_bus.publish_task_created(
            task_id=task_id,
            capability=capability,
            goal=goal,
            payload=payload,
        )
        self._schedule_worker_start(
            task_id=task_id,
            capability=capability,
            goal=goal,
            payload=payload,
            engine_pool=engine_pool,
            tool_runner=tool_runner,
            initial_answer=None,
        )
        log.info(
            "supervisor.spawn_subagent",
            user_id=self.user_id,
            task_id=task_id,
            capability=capability,
        )
        return task_id

    def _schedule_worker_start(
        self,
        *,
        task_id: str,
        capability: str,
        goal: str,
        payload: dict[str, Any],
        engine_pool: EnginePool,
        tool_runner: ToolRunner,
        initial_answer: tuple[str, Literal["reply", "amendment"]] | None,
    ) -> None:
        existing = self._worker_tasks.get(task_id)
        if existing is not None and not existing.done():
            if initial_answer is not None:
                self._pending_task_answers[task_id] = initial_answer
            return

        async def _run_with_slot() -> None:
            worker: SubAgentWorker | None = None
            slot_assigned = False
            slot_id: int | None = None
            try:
                slot_id = await engine_pool.assign_slot(task_id, "subagent")
                slot_assigned = True
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
                pending_answer = self._pending_task_answers.pop(task_id, None)
                answer = pending_answer or initial_answer
                if answer is not None:
                    await worker.resume_with(answer[0], mode=answer[1])
                log.info(
                    "supervisor.subagent_slot_ready",
                    user_id=self.user_id,
                    task_id=task_id,
                    capability=capability,
                    slot_id=slot_id,
                )
                await worker.run()
            except asyncio.CancelledError:
                if worker is not None:
                    worker.cancel()
                raise
            finally:
                if worker is None and slot_assigned:
                    await engine_pool.free_slot(task_id)
                self._workers.pop(task_id, None)
                self._worker_tasks.pop(task_id, None)

        self._worker_tasks[task_id] = asyncio.create_task(
            _run_with_slot(),
            name=f"subagent-{task_id[:8]}",
        )

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
            self._schedule_worker_start(
                task_id=task_id,
                capability=row.capability,
                goal=row.goal,
                payload=row.payload,
                engine_pool=engine_pool,
                tool_runner=tool_runner,
                initial_answer=(answer, mode),
            )
        else:
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
        self._pending_task_answers.pop(task_id, None)
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

    @staticmethod
    def _ensure_visible_reply(visible: str) -> str:
        text = visible.strip()
        if text and not contains_directive_leak(text):
            return text
        if text and contains_directive_leak(text):
            log.warning("supervisor.directive_leak_fallback")
            return _EMPTY_ASSISTANT_FALLBACK
        log.warning("supervisor.empty_assistant_fallback")
        return _EMPTY_ASSISTANT_FALLBACK

    def _build_main_messages(
        self,
        *,
        user_text: str,
        warm_profile: str,
        history: list,
        compressed_summary: str,
        injected_context: str,
        task_board_block: str,
    ) -> list[dict[str, Any]]:
        history_lines = [f"{turn.role}: {turn.text}" for turn in history]
        return build_main_chat_messages(
            MainPromptContext(
                user_text=user_text,
                warm_profile=warm_profile,
                history_lines=history_lines,
                compressed_summary=compressed_summary,
                recall_context=injected_context,
                task_board_block=task_board_block,
            ),
        )

    async def _ground_lookup_answer(
        self,
        *,
        user_text: str,
        visible: str,
        delegate_runs: list[DelegateRun],
        tool_runner: ToolRunner | None,
        turn_id: str,
        on_tool_event: ToolEventEmitter | None,
    ) -> tuple[str, list[DelegateRun], bool]:
        """Replace acks, leaks, and hallucinated prices with real search snippets."""
        if not needs_web_search_synthesis(visible, delegate_runs):
            return sanitize_spoken_prose(visible), delegate_runs, False

        runs = list(delegate_runs)
        has_ok_search = any(
            r.tool_name == "web_search" and r.result.status == "ok" for r in runs
        )
        if not has_ok_search and tool_runner is not None:
            search_query = fallback_web_search_query(
                user_text=user_text,
                model_content=visible,
            )
            emergency_call = ParsedToolCall(
                id="call_emergency_web_search",
                name="web_search",
                arguments=json.dumps(
                    {"query": search_query, "max_results": 8, "search_depth": "basic"},
                    ensure_ascii=False,
                ),
            )
            log.warning(
                "supervisor.emergency_web_search",
                user_id=self.user_id,
                session_id=self.session_id,
                query=search_query[:120],
            )
            runs = await run_native_tool_calls(
                user_id=self.user_id,
                turn_id=turn_id,
                tool_calls=[emergency_call],
                runner=tool_runner,
                on_event=on_tool_event,
            )

        synthesized = speak_web_search_results(runs)
        if synthesized:
            log.info(
                "supervisor.web_search_speech_fallback",
                user_id=self.user_id,
                session_id=self.session_id,
                chars=len(synthesized),
            )
            return sanitize_spoken_prose(synthesized), runs, True

        return sanitize_spoken_prose(visible), runs, False

    async def _answer_after_web_search(
        self,
        *,
        user_text: str,
        warm_profile: str,
        history: list,
        compressed_summary: str,
        task_board_block: str,
        spoken_ack: str,
        delegate_runs: list[DelegateRun],
        engine_pool: EnginePool,
        on_token: Callable[[str], Awaitable[None]] | None,
    ) -> tuple[str, bool]:
        """Prefer search snippets over a streaming LLM follow-up for web_search."""
        streamed = on_token is not None
        if is_web_search_only_runs(delegate_runs):
            synthesized = speak_web_search_results(delegate_runs)
            if synthesized:
                return synthesized, streamed
        follow_up_text = await self._follow_up_after_tool_runs(
            user_text=user_text,
            warm_profile=warm_profile,
            history=history,
            compressed_summary=compressed_summary,
            task_board_block=task_board_block,
            spoken_ack=spoken_ack,
            delegate_runs=delegate_runs,
            engine_pool=engine_pool,
            on_token=None if is_web_search_only_runs(delegate_runs) else on_token,
        )
        if needs_web_search_synthesis(follow_up_text, delegate_runs):
            synthesized = speak_web_search_results(delegate_runs)
            if synthesized:
                return synthesized, streamed
        return follow_up_text, False

    async def _follow_up_after_tool_runs(
        self,
        *,
        user_text: str,
        warm_profile: str,
        history: list,
        compressed_summary: str,
        task_board_block: str,
        spoken_ack: str,
        delegate_runs: list[DelegateRun],
        engine_pool: EnginePool,
        on_token: Callable[[str], Awaitable[None]] | None,
    ) -> str:
        """Second pass: inject tool snippets as text (Gemma-friendly vs role=tool)."""
        injected = build_follow_up_context(
            recall_block="",
            spawn_blocks=[],
            delegate_runs=delegate_runs,
        )
        if spoken_ack.strip():
            injected = (
                f"{injected}\n\nDo not repeat this opening: {spoken_ack.strip()}"
                if injected.strip()
                else f"Do not repeat this opening: {spoken_ack.strip()}"
            )
        return await self._complete(
            user_text=user_text,
            warm_profile=warm_profile,
            history=history,
            compressed_summary=compressed_summary,
            injected_context=injected,
            task_board_block=task_board_block,
            engine_pool=engine_pool,
            on_token=on_token,
            allow_delegates=False,
            completion_mode="answer",
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
        completion_mode: CompletionMode | None = None,
        retry_on_empty: bool = True,
        use_stream: bool = True,
        temperature: float = 0.7,
    ) -> str:
        history_lines = [f"{turn.role}: {turn.text}" for turn in history]
        if injected_context.strip() and "[TOOL_RESULT" in injected_context:
            history_lines = _history_for_tool_follow_up(history_lines)
        context = injected_context
        if not allow_delegates:
            no_delegate_instruction = (
                "Do not use tools or emit [DELEGATE], [REMEMBER], or [RECALL] "
                "in this reply. Answer directly in plain spoken prose."
            )
            context = (
                f"{context}\n\n{no_delegate_instruction}"
                if context
                else no_delegate_instruction
            )
        mode: CompletionMode = completion_mode or (
            "plan" if allow_delegates else "answer"
        )
        prompt = build_main_chat_messages(
            MainPromptContext(
                user_text=user_text,
                warm_profile=warm_profile,
                history_lines=history_lines,
                compressed_summary=compressed_summary,
                recall_context=context,
                task_board_block=task_board_block,
            ),
        )
        request = CompletionRequest(
            prompt=prompt,
            stop=("```", "[TOOL_RESULT", "[SUBAGENT_SPAWN"),
            max_tokens=_max_tokens_for_mode(mode),
            cache_prompt=allow_delegates,
            stream=use_stream,
            temperature=temperature,
            pin_slot=True,
        )
        log.debug(
            "llm.request",
            user_id=self.user_id,
            session_id=self.session_id,
            allow_delegates=allow_delegates,
            completion_mode=mode,
            prompt_chars=len(json.dumps(prompt)) if isinstance(prompt, list) else len(prompt),
            max_tokens=request.max_tokens,
            stream=use_stream,
            pin_slot=True,
        )
        handle = await engine_pool.submit(
            request, CompletionPriority.P0_MAIN, slot_hint=None
        )

        full_text = ""
        async for token in handle:
            full_text += token
            if on_token is not None:
                await on_token(token)
        if not full_text.strip():
            prompt_log = (
                json.dumps(prompt, ensure_ascii=False)
                if isinstance(prompt, list)
                else prompt
            )
            head = prompt_log[:200].replace("\n", "\\n")
            tail = prompt_log[-200:].replace("\n", "\\n")
            log.warning(
                "llm.empty_response",
                user_id=self.user_id,
                session_id=self.session_id,
                allow_delegates=allow_delegates,
                prompt_chars=len(prompt_log),
                prompt_head=head,
                prompt_tail=tail,
            )
            if retry_on_empty:
                retry_context = (
                    "The previous model pass returned no visible text. "
                    "Answer the user directly in one or two short spoken sentences."
                )
                if injected_context.strip():
                    retry_context = f"{injected_context}\n\n{retry_context}"
                return await self._complete(
                    user_text=user_text,
                    warm_profile=warm_profile,
                    history=history,
                    compressed_summary=compressed_summary,
                    injected_context=retry_context,
                    task_board_block=task_board_block,
                    engine_pool=engine_pool,
                    on_token=on_token,
                    allow_delegates=False,
                    completion_mode="retry",
                    retry_on_empty=False,
                    use_stream=False,
                    temperature=0.85,
                )
        log.debug(
            "llm.response",
            user_id=self.user_id,
            session_id=self.session_id,
            allow_delegates=allow_delegates,
            output_chars=len(full_text),
        )
        return full_text
