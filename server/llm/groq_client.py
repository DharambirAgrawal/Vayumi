# =============================================================================
# server/llm/groq_client.py — Groq API Wrapper
# =============================================================================
#
# PURPOSE:
#   Wraps the Groq API for LLM inference. Groq is the PRIMARY provider
#   for most tasks due to its extremely fast inference (low latency),
#   which is critical for natural conversational flow.
#
# MODELS USED VIA GROQ:
#   - llama-3.1-8b-instant: Fast routing, orchestration, memory, search queries
#   - llama-3.3-70b-versatile: Task execution, multi-step reasoning
#   - whisper-large-v3: STT (handled by server/voice/stt.py, not this file)
#
# CLASS: GroqClient
#
#   __init__(self, api_key: str | None = None):
#     - api_key loaded from env var GROQ_API_KEY if not provided
#     - self.client = AsyncGroq(api_key=api_key)
#
#   async def chat(self, model: str, messages: list[dict],
#                  stream: bool = False, max_tokens: int = 1000) -> str | AsyncIterator:
#     Makes a chat completion call to Groq API.
#     Parameters:
#       model: Groq model name (e.g. "llama-3.1-8b-instant")
#       messages: List of message dicts [{role, content}, ...]
#       stream: If True, returns an async iterator yielding tokens
#       max_tokens: Maximum response tokens
#     Non-streaming:
#       response = await self.client.chat.completions.create(...)
#       return response.choices[0].message.content
#     Streaming:
#       stream_obj = await self.client.chat.completions.create(stream=True, ...)
#       yields each token via async for chunk in stream_obj
#     Error handling:
#       - Rate limit (429) → raise so LLMRouter can fallback to Gemini
#       - Timeout → raise
#       - Other API errors → raise with descriptive message
#
# IMPORTS NEEDED:
# =============================================================================

import os

from groq import AsyncGroq


class GroqClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.client = AsyncGroq(api_key=self.api_key)

    async def chat(self, model: str, messages: list[dict],
                   stream: bool = False, max_tokens: int = 1000):
        pass
