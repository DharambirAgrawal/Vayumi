from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from server.engine.pool import (
    CompletionPriority,
    CompletionRequest,
    EnginePool,
    ParsedToolCall,
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
from server.memory.summarizer import schedule_session_summarization
from server.memory.warm import build_warm_profile
from server.orchestrator.directives import (
    DelegateDirective,
    RecallDirective,
    RecallDocDirective,
    RememberDirective,
    contains_directive_leak,
    execute_directives,
    filter_profile_directives,
    format_recall_results,
    parse_answer_to_directives,
    parse_delegate_directives,
    parse_directives,
    parse_respond_via_override,
    parse_search_directives,
    parse_stop_task_directives,
    plan_acknowledgment,
    strip_directives,
)
from server.orchestrator.prose import (
    finalize_assistant_prose,
    sanitize_spoken_prose,
)
from server.orchestrator.signal_bus import SignalBus, TaskEventEmitter
from server.orchestrator.task_board import TaskBoard
from server.orchestrator.tool_dispatch import (
    build_follow_up_context,
    format_subagent_spawn_block,
    run_main_tool_calls,
    split_delegate_directives,
)
from server.subagents.worker import SUB_CAPABILITIES, SubAgentWorker
from server.tools.registry import render_tool_result_for_prompt
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

        # Fetch context in parallel — three independent remote-DB reads that
        # otherwise serialize and add round-trips to the time-to-first-token.
        # append_turn runs after so it cannot race the history read (which must
        # exclude the current user turn — it is passed separately to the prompt).
        warm, history, summary = await asyncio.gather(
            build_warm_profile(self.user_id),
            recent_turns(self.session_id, limit=8),
            compressed_history(self.session_id),
        )
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
            schedule_session_summarization(
                session_id=self.session_id,
                user_id=self.user_id,
                engine_pool=engine_pool,
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

        # Pass 1 — non-streaming so we can see the whole decision (a [SEARCH] /
        # [DELEGATE] / [REMEMBER] / [RECALL] directive, or a plain answer) before
        # acting. We do NOT pass native function tools: Gemma 3n does not emit
        # OpenAI tool_calls, so the main agent drives tools via text directives.
        if tool_runner is not None:
            first = await engine_pool.complete_chat(
                CompletionRequest(
                    prompt=messages,
                    max_tokens=_max_tokens_for_mode("answer"),
                    cache_prompt=True,
                    stream=False,
                    temperature=0.7,
                    stop=("[TOOL_RESULT", "[SUBAGENT_SPAWN"),
                ),
            )
            raw_text = first.content or ""
        else:
            raw_text = await self._complete(
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

        spawn_blocks: list[str] = []
        remembers: list[RememberDirective] = []
        profile_directives: list = []
        follow_up_text = ""
        search_directives = parse_search_directives(raw_text)
        # The no-tool-runner branch already streamed via _complete(on_token=...).
        streamed_to_token = tool_runner is None

        if search_directives and tool_runner is not None:
            # [SEARCH query="..."] — Gemma's reliable web-lookup directive. Run the
            # search, feed results back as role:tool messages, then STREAM the
            # grounded answer to TTS. No snippet bypass, no regex, no re-voicing.
            ack = plan_acknowledgment(raw_text)
            if on_status_caption is not None:
                await on_status_caption(
                    sanitize_spoken_prose(ack) if ack else "One sec."
                )

            search_calls = [
                ParsedToolCall(
                    id=f"call_search_{i}",
                    name="web_search",
                    arguments=json.dumps(
                        {"query": d.query, "max_results": 8}, ensure_ascii=False
                    ),
                )
                for i, d in enumerate(search_directives[:2])
            ]
            runs = await run_main_tool_calls(
                user_id=self.user_id,
                turn_id=tid,
                tool_calls=search_calls,
                runner=tool_runner,
                on_event=on_tool_event,
                # Always announce intent (Rule 9), even when the model emitted
                # only the [SEARCH] directive with no spoken opening line.
                event_label_start=ack or "Searching the web",
            )
            # Ground the answer by injecting the results as TEXT into a normal
            # alternating chat. Gemma's chat template rejects role:tool / assistant
            # tool_calls (it requires strict user/assistant alternation), so we
            # must not feed an OpenAI tool round-trip here.
            results_block = "\n\n".join(
                render_tool_result_for_prompt(run.call.name, run.result)
                for run in runs
            )
            follow_up_text = await self._answer_from_search(
                user_text=user_text,
                results_block=results_block,
                engine_pool=engine_pool,
                on_token=on_token,
            )
            streamed_to_token = bool(follow_up_text.strip())
            raw_text = follow_up_text or raw_text
        else:
            # No native tool call — handle directives: task control, memory,
            # recall, and background sub-agent delegation.
            await self._apply_task_directives(
                raw_text,
                engine_pool=engine_pool,
                tool_runner=tool_runner,
            )

            profile_directives = filter_profile_directives(parse_directives(raw_text))
            recall_results = await execute_directives(self.user_id, profile_directives)

            _, sub_directives = split_delegate_directives(
                parse_delegate_directives(raw_text)
            )

            async def _spawn_one(directive: DelegateDirective) -> str | None:
                cap = directive.capability.lower()
                if cap not in SUB_CAPABILITIES:
                    return None
                existing = self.task_board.find_running(cap, directive.goal)
                if existing is not None:
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

            if sub_directives and tool_runner is not None:
                spawn_tasks = [
                    asyncio.create_task(_spawn_one(d), name=f"spawn-{tid[:8]}")
                    for d in sub_directives
                ]
                for result in await asyncio.gather(*spawn_tasks):
                    if isinstance(result, str):
                        spawn_blocks.append(result)

            recalls = [
                d
                for d in profile_directives
                if isinstance(d, (RecallDirective, RecallDocDirective))
            ]
            remembers = [
                d for d in profile_directives if isinstance(d, RememberDirective)
            ]
            recall_block = (
                format_recall_results(recall_results)
                if recalls and recall_results
                else ""
            )

            # When work was delegated or a fact recalled, the pass-1 output is an
            # internal plan — never speak it. Surface the model's clean opening
            # line as a status, then stream a clean answer grounded in the recall
            # value and spawn notes.
            if spawn_blocks or recall_block:
                ack = plan_acknowledgment(raw_text)
                if ack and on_status_caption is not None:
                    await on_status_caption(sanitize_spoken_prose(ack))
                follow_up_text = await self._complete(
                    user_text=user_text,
                    warm_profile=warm,
                    history=await recent_turns(self.session_id, limit=8),
                    compressed_summary=summary,
                    injected_context=build_follow_up_context(
                        recall_block=recall_block,
                        spawn_blocks=spawn_blocks,
                    ),
                    task_board_block=self.task_board.render_for_main(),
                    engine_pool=engine_pool,
                    on_token=on_token,
                    allow_delegates=False,
                    completion_mode="answer",
                )
                streamed_to_token = bool(follow_up_text.strip())
                # Discard the leaky pass-1 plan; the clean second pass is the reply.
                raw_text = follow_up_text

        answer_raw = follow_up_text or raw_text
        visible = finalize_assistant_prose(strip_directives(answer_raw))
        if contains_directive_leak(visible):
            visible = ""
        visible = sanitize_spoken_prose(visible)

        if not visible.strip():
            if spawn_blocks:
                visible = "Okay, I'm looking into that now."
            elif remembers:
                visible = "Got it — I'll remember that."

        # When the answer came from a non-streaming pass (plain pass-1 prose, no
        # tools, no recall), push it through the token path so TTS still plays it.
        if not streamed_to_token and on_token is not None and visible.strip():
            await on_token(visible)
            streamed_to_token = True

        override = parse_respond_via_override(answer_raw)
        respond_via = apply_respond_via_override(override, computed_respond_via)

        visible = self._ensure_visible_reply(visible)
        if visible.strip():
            await append_turn(self.session_id, self.user_id, "assistant", visible)

        schedule_session_summarization(
            session_id=self.session_id,
            user_id=self.user_id,
            engine_pool=engine_pool,
        )

        log.info(
            "supervisor.turn_complete",
            user_id=self.user_id,
            session_id=self.session_id,
            profile_directives=len(profile_directives),
            spawns=len(spawn_blocks),
            searches=len(search_directives),
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

    async def _answer_from_search(
        self,
        *,
        user_text: str,
        results_block: str,
        engine_pool: EnginePool,
        on_token: Callable[[str], Awaitable[None]] | None,
    ) -> str:
        """Stream a spoken answer grounded in fresh web results.

        Uses a dedicated grounding system prompt — NOT main.txt — because
        main.txt tells the model it "MUST [SEARCH]" for live data, which makes it
        re-emit a [SEARCH] directive instead of answering from the results.
        """
        system = (
            "You are Vayumi, speaking aloud to a friend. Fresh web search results "
            "are given below. Answer the user's question in one or two short spoken "
            "sentences using ONLY these results — state the real number or fact. "
            "Plain spoken prose: no markdown, no URLs, no lists. The search is "
            "already done — do NOT ask to search again and do NOT emit any "
            "directive or bracketed tag."
        )
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Question: {user_text}\n\nSearch results:\n{results_block}",
            },
        ]
        request = CompletionRequest(
            prompt=messages,
            stop=("[SEARCH", "[DELEGATE", "[TOOL_RESULT", "[REMEMBER", "[RECALL"),
            max_tokens=_max_tokens_for_mode("answer"),
            cache_prompt=False,
            stream=True,
            temperature=0.5,
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
        return full_text

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
