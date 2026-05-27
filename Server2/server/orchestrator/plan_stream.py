from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from server.orchestrator.directives import parse_delegate_directives, plan_acknowledgment
from server.orchestrator.prose import sanitize_spoken_prose
from server.voice.sentence_buffer import drain_complete_sentences

OnStatusCaption = Callable[[str], Awaitable[None]]
OnDelegatesReady = Callable[[str], Awaitable[None]]


class PlanStreamHandler:
    """
    One plan LLM call: stream tokens, speak the first sentence (ack) as soon as
    it is complete, then notify when complete [DELEGATE] blocks arrive so tools
    can start while the model may still be generating.
    """

    def __init__(
        self,
        *,
        on_status_caption: OnStatusCaption | None = None,
        on_delegates_ready: OnDelegatesReady | None = None,
    ) -> None:
        self._buffer = ""
        self._on_status = on_status_caption
        self._on_delegates_ready = on_delegates_ready
        self.ack_sent = False
        self.raw_text = ""
        self._complete_delegate_blocks = 0

    async def on_token(self, token: str) -> None:
        if not token:
            return
        self._buffer += token
        self.raw_text += token
        await self._maybe_emit_ack()
        await self._maybe_notify_delegates()

    async def finalize(self) -> str:
        if not self.ack_sent and self._on_status is not None:
            ack = plan_acknowledgment(self.raw_text)
            if ack:
                await self._on_status(ack)
                self.ack_sent = True
        return self.raw_text

    async def _maybe_emit_ack(self) -> None:
        if self.ack_sent or self._on_status is None:
            return
        head = self._prose_before_delegate(self._buffer)
        if not head:
            return
        # Try complete sentences first
        sentences, _ = drain_complete_sentences(head)
        if sentences:
            first = sanitize_spoken_prose(sentences[0])
            if len(first) >= 5:
                await self._on_status(first)
                self.ack_sent = True
                return
        # Fallback: fire on word count only when delegate block is imminent
        # (avoids ack without punctuation, then the same line again from TTS feed).
        clean = sanitize_spoken_prose(head.strip())
        words = clean.split()
        if (
            len(words) >= 6
            and len(clean) >= 20
            and re.search(r"\[DELEGATE\b", self._buffer, re.IGNORECASE)
        ):
            await self._on_status(clean)
            self.ack_sent = True

    async def _maybe_notify_delegates(self) -> None:
        if self._on_delegates_ready is None:
            return
        count = len(parse_delegate_directives(self._buffer))
        if count <= self._complete_delegate_blocks:
            return
        if not self.ack_sent and self._on_status is not None:
            head = self._prose_before_delegate(self._buffer).strip()
            words = head.split()
            if len(words) >= 6 and len(head) >= 20:
                return
        self._complete_delegate_blocks = count
        await self._on_delegates_ready(self._buffer)

    @staticmethod
    def _prose_before_delegate(text: str) -> str:
        match = re.search(r"\[DELEGATE\b", text, re.IGNORECASE)
        if match:
            return text[: match.start()]
        return text
