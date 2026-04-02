# =============================================================================
# server/llm/gemini_client.py — Google Gemini API Wrapper
# =============================================================================
#
# PURPOSE:
#   Wraps the Google Gemini API for LLM inference. Gemini serves as:
#   1. FALLBACK when Groq is rate-limited
#   2. PRIMARY for complex reasoning tasks that need stronger models
#
# MODELS USED VIA GEMINI:
#   - gemini-2.0-flash: Default fallback for most tasks (fast, capable)
#   - gemini-1.5-pro: Complex reasoning tasks that need high intelligence
#
# CLASS: GeminiClient
#
#   __init__(self, api_key: str | None = None):
#     - api_key loaded from env var GEMINI_API_KEY if not provided
#     - Configures google.generativeai with api_key
#
#   async def chat(self, model: str, messages: list[dict],
#                  stream: bool = False, max_tokens: int = 1000) -> str | AsyncIterator:
#     Makes a chat completion call to Gemini API.
#     Parameters:
#       model: Gemini model name (e.g. "gemini-2.0-flash")
#       messages: List of message dicts [{role, content}, ...]
#                 Note: Gemini uses "user"/"model" roles, not "user"/"assistant".
#                 This function handles the conversion.
#       stream: If True, returns an async iterator yielding tokens
#       max_tokens: Maximum response tokens (maps to max_output_tokens in Gemini)
#     Non-streaming:
#       model_obj = genai.GenerativeModel(model)
#       response = model_obj.generate_content(contents, generation_config={...})
#       return response.text
#     Streaming:
#       response = model_obj.generate_content(contents, stream=True, ...)
#       yields each chunk.text via async iteration
#     Error handling:
#       - Timeout → raise
#       - API errors → raise with descriptive message
#       - Safety filters triggered → return safe fallback message
#
#   def _convert_messages(self, messages: list[dict]) -> list:
#     Converts OpenAI-style messages to Gemini format.
#     "system" role → prepended to first user message
#     "assistant" → "model"
#     "user" → "user"
#
# IMPORTS NEEDED:
# =============================================================================

import os

import google.generativeai as genai


class GeminiClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        genai.configure(api_key=self.api_key)

    async def chat(self, model: str, messages: list[dict],
                   stream: bool = False, max_tokens: int = 1000):
        pass

    def _convert_messages(self, messages: list[dict]) -> list:
        pass
