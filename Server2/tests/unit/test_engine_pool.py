from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from server.engine.pool import (
    CompletionPriority,
    CompletionRequest,
    EnginePool,
    parse_completion_stream_line,
)


class FakeCompletionClient:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.calls: list[tuple[str, int, str]] = []

    def stream_completion(
        self,
        *,
        base_url: str,
        slot_id: int,
        request: CompletionRequest,
    ) -> AsyncIterator[str]:
        return self._stream(base_url, slot_id, request)

    async def _stream(
        self,
        base_url: str,
        slot_id: int,
        request: CompletionRequest,
    ) -> AsyncIterator[str]:
        self.calls.append((base_url, slot_id, request.prompt))
        for token in self.tokens:
            yield token


@pytest.mark.asyncio
async def test_engine_pool_streams_tokens_on_sticky_slot() -> None:
    client = FakeCompletionClient(["hello", " ", "world"])
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=client,
    )
    pool.start()

    try:
        handle = await pool.submit(
            CompletionRequest(prompt="User: hi"),
            CompletionPriority.P0_MAIN,
            slot_hint=0,
        )
        tokens = [token async for token in handle]
    finally:
        await pool.close()

    assert tokens == ["hello", " ", "world"]
    assert client.calls == [("http://127.0.0.1:8081", 0, "User: hi")]


@pytest.mark.asyncio
async def test_engine_pool_rejects_invalid_slot_hint() -> None:
    pool = EnginePool(base_url="http://127.0.0.1:8081", parallel_slots=2)
    pool.start()

    try:
        with pytest.raises(ValueError):
            await pool.submit(
                CompletionRequest(prompt="User: hi"),
                CompletionPriority.P0_MAIN,
                slot_hint=2,
            )
    finally:
        await pool.close()


def test_parse_completion_stream_line_handles_llama_content() -> None:
    assert parse_completion_stream_line('data: {"content":"hello"}') == "hello"
    assert parse_completion_stream_line('{"choices":[{"delta":{"content":"x"}}]}') == "x"
    assert parse_completion_stream_line("") is None
    assert parse_completion_stream_line("data: [DONE]") is None
