from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

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
    format_recall_results,
    parse_directives,
    strip_directives,
)

log = get_logger("orchestrator.supervisor")


@dataclass(frozen=True)
class TurnOutput:
    assistant_text: str
    raw_text: str


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

    async def run_turn(
        self,
        user_text: str,
        *,
        engine_pool: EnginePool,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> TurnOutput:
        await self.ensure_session()
        user_text = user_text.strip()
        if not user_text:
            return TurnOutput(assistant_text="", raw_text="")

        warm = await build_warm_profile(self.user_id)
        history = await recent_turns(self.session_id, limit=8)
        summary = await compressed_history(self.session_id)
        await append_turn(self.session_id, self.user_id, "user", user_text)

        raw_text = await self._complete(
            user_text=user_text,
            warm_profile=warm,
            history=history,
            compressed_summary=summary,
            recall_context="",
            engine_pool=engine_pool,
            on_token=on_token,
        )

        directives = parse_directives(raw_text)
        recall_results = await execute_directives(self.user_id, directives)

        recalls = [d for d in directives if isinstance(d, RecallDirective)]
        remembers = [d for d in directives if isinstance(d, RememberDirective)]

        follow_up_text = ""
        if recalls and recall_results:
            recall_context = format_recall_results(recall_results)
            follow_up_text = await self._complete(
                user_text=user_text,
                warm_profile=warm,
                history=history,
                compressed_summary=summary,
                recall_context=recall_context,
                engine_pool=engine_pool,
                on_token=on_token,
            )
            raw_text = follow_up_text or raw_text

        visible = strip_directives(follow_up_text or raw_text)
        if not visible.strip() and remembers and not recalls:
            warm = await build_warm_profile(self.user_id)
            visible = "Got it — I'll remember that."

        await append_turn(self.session_id, self.user_id, "assistant", visible)

        log.info(
            "supervisor.turn_complete",
            user_id=self.user_id,
            session_id=self.session_id,
            directives=len(directives),
        )
        return TurnOutput(assistant_text=visible, raw_text=raw_text)

    async def _complete(
        self,
        *,
        user_text: str,
        warm_profile: str,
        history: list,
        compressed_summary: str,
        recall_context: str,
        engine_pool: EnginePool,
        on_token: Callable[[str], Awaitable[None]] | None,
    ) -> str:
        history_lines = [f"{turn.role}: {turn.text}" for turn in history]
        prompt = build_main_prompt(
            MainPromptContext(
                user_text=user_text,
                warm_profile=warm_profile,
                history_lines=history_lines,
                compressed_summary=compressed_summary,
                recall_context=recall_context,
            )
        )
        request = CompletionRequest(prompt=prompt)
        handle = await engine_pool.submit(request, CompletionPriority.P0_MAIN, slot_hint=0)

        full_text = ""
        async for token in handle:
            full_text += token
            if on_token is not None:
                await on_token(token)
        return full_text
