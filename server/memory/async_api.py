from __future__ import annotations

import asyncio
from typing import Optional

from memory import MemorySystem
from memory.models import MemoryType


class AsyncMemorySystem:
    """Async wrapper around the synchronous MemorySystem API."""

    def __init__(self, memory: MemorySystem):
        self._memory = memory

    async def search(self, *args, **kwargs):
        return await asyncio.to_thread(self._memory.search, *args, **kwargs)

    async def ingest(self, *args, **kwargs):
        return await asyncio.to_thread(self._memory.ingest, *args, **kwargs)

    async def save(
        self,
        content: str,
        memory_type: MemoryType,
        speaker_id: Optional[str] = None,
        expires_at: Optional[str] = None,
    ):
        return await asyncio.to_thread(
            self._memory.save,
            content,
            memory_type,
            speaker_id,
            expires_at,
        )

    async def delete(self, memory_id: str, speaker_id: Optional[str] = None):
        return await asyncio.to_thread(self._memory.delete, memory_id, speaker_id)

    async def update(self, memory_id: str, new_content: str, speaker_id: Optional[str] = None):
        return await asyncio.to_thread(self._memory.update, memory_id, new_content, speaker_id)

    async def get_user_model(self, speaker_id: Optional[str] = None):
        return await asyncio.to_thread(self._memory.get_user_model, speaker_id)

    async def get_short_term(self):
        return await asyncio.to_thread(self._memory.get_short_term)

    async def add_turn(self, speaker_id: str, text: str):
        return await asyncio.to_thread(self._memory.add_turn, speaker_id, text)

    async def flush_session(self):
        return await asyncio.to_thread(self._memory.flush_session)
