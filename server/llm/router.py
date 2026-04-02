# =============================================================================
# server/llm/router.py — LLM Router (Groq Primary, Gemini Fallback)
# =============================================================================
#
# PURPOSE:
#   Routes LLM requests to the appropriate provider and model based on
#   task type, estimated tokens, and rate limit availability. Groq is the
#   primary provider (fast inference, low latency). Gemini is the fallback
#   when Groq is rate-limited and the primary for complex reasoning tasks.
#
# MODEL ROUTING TABLE (from doc Section 14.1):
#   Orchestrator:        Fast + cheap     → Groq llama-3.1-8b-instant    | Fallback: Gemini 2.0 flash
#   Task Agent:          Smart, multi-step→ Groq llama-3.3-70b-versatile | Fallback: Gemini 2.0 flash
#   Memory Agent:        Summarization    → Groq llama-3.1-8b-instant    | No fallback
#   Search Agent:        Query + summary  → Groq llama-3.1-8b-instant    | No fallback
#   Complex reasoning:   High intelligence→ Gemini 2.0 flash             | Fallback: Gemini 1.5 pro
#
# RATE LIMITS (Groq free tier):
#   llama-3.1-8b-instant:    RPM=30, TPM=131072
#   llama-3.3-70b-versatile: RPM=30, TPM=131072
#
# PER-USER RATE LIMITING:
#   Global Groq limits tracked globally, but per-user limiter ensures
#   one user cannot starve others.
#   Default: max_rpm_per_user=10, max_tpm_per_user=50000
#
# CLASS: LLMRouter
#
#   __init__(self, groq_client, gemini_client,
#            max_rpm_per_user=10, max_tpm_per_user=50000):
#     - self.groq_client = groq_client (server.llm.groq_client.GroqClient)
#     - self.gemini_client = gemini_client (server.llm.gemini_client.GeminiClient)
#     - self.groq_limits = {model: {rpm, tpm}} — global rate tracking
#     - self.per_user_limiter = PerUserRateLimiter(max_rpm, max_tpm)
#     - self._lock = asyncio.Lock() — for atomic rate limit checks
#
#   async def route(self, user_id: str, task_type: str,
#                   estimated_tokens: int) -> tuple[str, str] | tuple[None, str]:
#     Determines which provider + model to use.
#     Steps:
#       1. Check per-user rate limit → reject if exceeded
#       2. Select Groq model via _select_groq_model(task_type)
#       3. Check global Groq rate limit for that model
#       4. If within Groq limits → return ("groq", model_name)
#       5. If Groq rate-limited → return ("gemini", _select_gemini_model(task_type))
#     Returns: (provider, model) or (None, error_message)
#
#   async def call(self, user_id: str, task_type: str, messages: list[dict],
#                  stream: bool = False, max_tokens: int = 1000) -> str | AsyncIterator:
#     High-level call: routes and executes.
#     Steps:
#       1. Estimate tokens from messages
#       2. Call self.route(user_id, task_type, estimated_tokens)
#       3. If provider is "groq" → call groq_client.chat(model, messages, stream, max_tokens)
#       4. If provider is "gemini" → call gemini_client.chat(model, messages, stream, max_tokens)
#       5. Update rate limit counters
#       6. Return response text or async iterator (if streaming)
#
#   def _select_groq_model(self, task_type: str) -> str:
#     "orchestrate" | "memory" | "search" → "llama-3.1-8b-instant"
#     "task" | "complex" → "llama-3.3-70b-versatile"
#
#   def _select_gemini_model(self, task_type: str) -> str:
#     "complex" → "gemini-1.5-pro"
#     default → "gemini-2.0-flash"
#
# CLASS: PerUserRateLimiter
#
#   __init__(self, max_rpm_per_user=10, max_tpm_per_user=50000):
#     self.user_usage: dict[str, dict] — {user_id: {rpm_count, tpm_count, window_start}}
#
#   def check(self, user_id: str, estimated_tokens: int) -> tuple[bool, str | None]:
#     Checks if user is within their per-user rate limits.
#     Returns (True, None) if OK, (False, error_message) if exceeded.
#     Resets window if elapsed > 60 seconds.
#
# IMPORTS NEEDED:
# =============================================================================

import asyncio
import time

from server.llm.groq_client import GroqClient
from server.llm.gemini_client import GeminiClient


class PerUserRateLimiter:
    def __init__(self, max_rpm_per_user: int = 10, max_tpm_per_user: int = 50000):
        self.max_rpm_per_user = max_rpm_per_user
        self.max_tpm_per_user = max_tpm_per_user
        self.user_usage: dict[str, dict] = {}

    def check(self, user_id: str, estimated_tokens: int) -> tuple[bool, str | None]:
        pass


class LLMRouter:
    GROQ_LIMITS = {
        "llama-3.1-8b-instant": {"rpm": 30, "tpm": 131072},
        "llama-3.3-70b-versatile": {"rpm": 30, "tpm": 131072},
    }

    def __init__(self, groq_client: GroqClient, gemini_client: GeminiClient,
                 max_rpm_per_user: int = 10, max_tpm_per_user: int = 50000):
        self.groq_client = groq_client
        self.gemini_client = gemini_client
        self.per_user_limiter = PerUserRateLimiter(max_rpm_per_user, max_tpm_per_user)
        self._lock = asyncio.Lock()

    async def route(self, user_id: str, task_type: str,
                    estimated_tokens: int) -> "tuple[str, str] | tuple[None, str]":
        pass

    async def call(self, user_id: str, task_type: str, messages: list[dict],
                   stream: bool = False, max_tokens: int = 1000):
        pass

    def _select_groq_model(self, task_type: str) -> str:
        pass

    def _select_gemini_model(self, task_type: str) -> str:
        pass
