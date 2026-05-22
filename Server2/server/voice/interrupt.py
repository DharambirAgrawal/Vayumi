from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from server.engine.pool import CompletionHandle
from server.logger import get_logger
from server.voice.types import SpeechState

log = get_logger("voice.interrupt")

InterruptSource = Literal["wake", "button", "voice"]


@dataclass
class InterruptController:
    """Owns the per-session speech state machine and cancel scopes."""

    state: SpeechState = SpeechState.IDLE
    turn_id: str = ""
    drop_next_utterance: bool = False
    _main_handle: CompletionHandle | None = field(default=None, repr=False)
    _turn_task: asyncio.Task[None] | None = field(default=None, repr=False)
    _tts_cancel: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def begin_listening(self) -> None:
        self.state = SpeechState.LISTENING
        self.drop_next_utterance = False

    def begin_thinking(self, turn_id: str) -> None:
        self.turn_id = turn_id
        self.state = SpeechState.THINKING

    def begin_speaking(self) -> None:
        self.state = SpeechState.SPEAKING
        self._tts_cancel.clear()

    def finish_turn(self) -> None:
        self.turn_id = ""
        self._main_handle = None
        self._turn_task = None
        self.state = SpeechState.IDLE

    def attach_turn_task(self, task: asyncio.Task[None]) -> None:
        self._turn_task = task

    def attach_main_handle(self, handle: CompletionHandle) -> None:
        self._main_handle = handle

    async def handle_interrupt(self, source: InterruptSource) -> None:
        log.info("interrupt.received", source=source, state=self.state.value, turn_id=self.turn_id)
        await self.cancel_main_decode(self.turn_id)
        await self.cancel_tts(self.turn_id)
        if source in ("wake", "voice"):
            self.drop_partial_utterance(f"interrupt:{source}")
        self.state = SpeechState.IDLE

    async def cancel_tts(self, turn_id: str) -> None:
        if turn_id and self.turn_id and turn_id != self.turn_id:
            return
        self._tts_cancel.set()

    async def cancel_main_decode(self, turn_id: str) -> None:
        if turn_id and self.turn_id and turn_id != self.turn_id:
            return
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
        if self._main_handle is not None:
            from server.engine.pool import cancel

            await cancel(self._main_handle)
            self._main_handle = None

    def drop_partial_utterance(self, reason: str) -> None:
        log.debug("interrupt.drop_partial_utterance", reason=reason)
        self.drop_next_utterance = True

    def should_drop_utterance(self) -> bool:
        if self.drop_next_utterance:
            self.drop_next_utterance = False
            return True
        return False

    def tts_cancelled(self) -> bool:
        return self._tts_cancel.is_set()
