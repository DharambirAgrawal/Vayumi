from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from server.voice.types import TranscriptEvent


class STTBackend(Protocol):
    async def transcribe_stream(
        self,
        chunks: AsyncIterator[bytes],
    ) -> AsyncIterator[TranscriptEvent]:
        ...
