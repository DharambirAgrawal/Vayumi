from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from server.engine.pool import (
    ChatCompletionResult,
    CompletionPriority,
    CompletionRequest,
    EnginePool,
    ParsedToolCall,
    extract_completion_text,
    parse_chat_completion,
    parse_completion_stream_line,
)


class FakeCompletionClient:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.calls: list[tuple[str, int | None, object]] = []

    def stream_completion(
        self,
        *,
        base_url: str,
        slot_id: int | None,
        request: CompletionRequest,
    ) -> AsyncIterator[str]:
        return self._stream(base_url, slot_id, request)

    async def _stream(
        self,
        base_url: str,
        slot_id: int | None,
        request: CompletionRequest,
    ) -> AsyncIterator[str]:
        self.calls.append((base_url, slot_id, request.prompt))
        for token in self.tokens:
            yield token

    async def complete_chat(
        self,
        *,
        base_url: str,
        slot_id: int | None,
        request: CompletionRequest,
    ) -> ChatCompletionResult:
        self.calls.append((base_url, slot_id, request.prompt))
        return ChatCompletionResult(content="tool phase", tool_calls=[])


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


@pytest.mark.asyncio
async def test_engine_pool_complete_chat_uses_client() -> None:
    client = FakeCompletionClient([])
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=2,
        completion_client=client,
    )
    pool.start()
    try:
        result = await pool.complete_chat(
            CompletionRequest(
                prompt=[{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "web_search"}}],
            )
        )
    finally:
        await pool.close()

    assert result.content == "tool phase"
    assert client.calls


def test_parse_completion_stream_line_handles_llama_content() -> None:
    assert parse_completion_stream_line('data: {"content":"hello"}') == "hello"
    assert parse_completion_stream_line('{"choices":[{"delta":{"content":"x"}}]}') == "x"
    assert parse_completion_stream_line("") is None
    assert parse_completion_stream_line("data: [DONE]") is None


def test_parse_completion_stream_line_skips_empty_llama_token_chunks() -> None:
    line = 'data: {"index":0,"content":"","tokens":[106],"stop":false}'
    assert parse_completion_stream_line(line) is None


def test_extract_completion_text_reads_top_level_fields() -> None:
    assert extract_completion_text({"content": "hi"}) == "hi"
    assert extract_completion_text({"text": "there"}) == "there"
    assert extract_completion_text({"choices": [{"text": "ok"}]}) == "ok"


def test_parse_chat_completion_reads_tool_calls() -> None:
    payload = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": '{"query":"btc"}',
                            },
                        }
                    ],
                },
            }
        ]
    }
    result = parse_chat_completion(payload)
    assert result.finish_reason == "tool_calls"
    assert result.content == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0] == ParsedToolCall(
        id="call_1",
        name="web_search",
        arguments='{"query":"btc"}',
    )
