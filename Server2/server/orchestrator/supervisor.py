from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

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
    RecallDirective,
    RememberDirective,
    execute_directives,
    filter_profile_directives,
    format_recall_results,
    parse_delegate_directives,
    parse_directives,
    parse_respond_via_override,
    strip_directives,
)
from server.orchestrator.prose import finalize_assistant_prose
from server.orchestrator.tool_dispatch import (
    DelegateRun,
    coerce_delegates_for_live_web,
    format_delegate_results,
    run_delegate_directives,
    tool_status_message,
    web_search_succeeded,
)
from server.orchestrator.tool_intent import suggest_web_search_query
from server.tools.runner import ToolEventEmitter, ToolRunner
from server.voice.respond_via import InputKind, RespondVia, apply_respond_via_override

log = get_logger("orchestrator.supervisor")

TurnKind = Literal["voice", "chat", "proactive", "system"]


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

    async def ensure_session(self, client_meta: dict | None = None) -> None:
        if self._ready:
            return
        await load_or_create_session(self.user_id, self.session_id, client_meta)
        self._ready = True

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
        on_status_caption: Callable[[str], Awaitable[None]] | None = None,
    ) -> TurnOutput:
        tid = turn_id or str(uuid.uuid4())
        await self.ensure_session()
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

        # Pass 1: plan tools / recall — do not stream to TTS (avoids speaking [DELEGATE] blocks).
        plan_on_token = None if tool_runner is not None else on_token
        raw_text = await self._complete(
            user_text=user_text,
            warm_profile=warm,
            history=history,
            compressed_summary=summary,
            injected_context="",
            engine_pool=engine_pool,
            on_token=plan_on_token,
        )

        profile_directives = filter_profile_directives(parse_directives(raw_text))
        recall_results = await execute_directives(self.user_id, profile_directives)

        delegate_directives = parse_delegate_directives(raw_text)
        if not delegate_directives and tool_runner is not None:
            auto_query = suggest_web_search_query(user_text)
            if auto_query:
                log.info(
                    "supervisor.auto_web_search",
                    user_id=self.user_id,
                    turn_id=tid,
                    query=auto_query[:80],
                )
                delegate_directives = coerce_delegates_for_live_web(user_text, [])
        elif tool_runner is not None:
            delegate_directives = coerce_delegates_for_live_web(
                user_text, delegate_directives
            )

        delegate_runs = []
        if delegate_directives and tool_runner is not None:
            if on_status_caption is not None:
                await on_status_caption(
                    tool_status_message(user_text, delegate_directives)
                )
            delegate_runs = await run_delegate_directives(
                user_id=self.user_id,
                turn_id=tid,
                directives=delegate_directives,
                runner=tool_runner,
                on_event=on_tool_event,
            )
            if suggest_web_search_query(user_text) and not web_search_succeeded(
                delegate_runs
            ):
                fallback = coerce_delegates_for_live_web(user_text, [])
                if on_status_caption is not None:
                    await on_status_caption(
                        tool_status_message(user_text, fallback)
                    )
                extra = await run_delegate_directives(
                    user_id=self.user_id,
                    turn_id=tid,
                    directives=fallback,
                    runner=tool_runner,
                    on_event=on_tool_event,
                )
                delegate_runs = [*delegate_runs, *extra]
        elif delegate_directives and tool_runner is None:
            log.warning(
                "supervisor.delegates_skipped",
                user_id=self.user_id,
                count=len(delegate_directives),
            )

        recalls = [d for d in profile_directives if isinstance(d, RecallDirective)]
        remembers = [d for d in profile_directives if isinstance(d, RememberDirective)]

        injected_parts: list[str] = []
        if recalls and recall_results:
            injected_parts.append(format_recall_results(recall_results))
        if delegate_runs:
            injected_parts.append(format_delegate_results(delegate_runs))

        follow_up_text = ""
        if injected_parts:
            injected_context = "\n\n".join(injected_parts)
            history = await recent_turns(self.session_id, limit=8)
            follow_up_text = await self._complete(
                user_text=user_text,
                warm_profile=warm,
                history=history,
                compressed_summary=summary,
                injected_context=injected_context,
                engine_pool=engine_pool,
                on_token=on_token,
                allow_delegates=False,
            )
            raw_text = follow_up_text or raw_text

        visible = finalize_assistant_prose(strip_directives(follow_up_text or raw_text))
        if not visible.strip() and remembers and not recalls and not delegate_runs:
            warm = await build_warm_profile(self.user_id)
            visible = "Got it — I'll remember that."
        if not visible.strip() and delegate_runs and not recalls:
            visible = _fallback_from_tools(delegate_runs)

        override = parse_respond_via_override(follow_up_text or raw_text)
        respond_via = apply_respond_via_override(override, computed_respond_via)

        await append_turn(self.session_id, self.user_id, "assistant", visible)

        log.info(
            "supervisor.turn_complete",
            user_id=self.user_id,
            session_id=self.session_id,
            profile_directives=len(profile_directives),
            delegates=len(delegate_runs),
            respond_via=respond_via,
            input_kind=input_kind,
        )
        return TurnOutput(
            assistant_text=visible,
            raw_text=raw_text,
            turn_id=tid,
            respond_via=respond_via,
        )

    async def _complete(
        self,
        *,
        user_text: str,
        warm_profile: str,
        history: list,
        compressed_summary: str,
        injected_context: str,
        engine_pool: EnginePool,
        on_token: Callable[[str], Awaitable[None]] | None,
        allow_delegates: bool = True,
    ) -> str:
        history_lines = [f"{turn.role}: {turn.text}" for turn in history]
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
            )
        )
        request = CompletionRequest(
            prompt=prompt,
            stop=("\n\n```", "\n```\n"),
        )
        handle = await engine_pool.submit(request, CompletionPriority.P0_MAIN, slot_hint=0)

        full_text = ""
        async for token in handle:
            full_text += token
            if on_token is not None:
                await on_token(token)
        return full_text


def _fallback_from_tools(delegate_runs: list[DelegateRun]) -> str:
    for run in delegate_runs:
        if run.result.status == "ok" and run.result.summary:
            return run.result.summary
    for run in delegate_runs:
        if run.result.summary:
            return run.result.summary
    return "I ran the requested tools but could not form a reply."
