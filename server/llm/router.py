# =============================================================================
# server/llm/router.py — LLM Router (Groq Primary, Gemini Fallback)
# =============================================================================

import asyncio
import time
import logging
from typing import AsyncIterator

from server.llm.groq_client import GroqClient
from server.llm.gemini_client import GeminiClient


logger = logging.getLogger(__name__)


class PerUserRateLimiter:
    """Per-user rate limiter to prevent one user from starving others."""
    
    def __init__(self, max_rpm_per_user: int = 10, max_tpm_per_user: int = 50000):
        self.max_rpm_per_user = max_rpm_per_user
        self.max_tpm_per_user = max_tpm_per_user
        self.user_usage: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def check(self, user_id: str, estimated_tokens: int) -> tuple[bool, str | None]:
        """
        Check if user is within their per-user rate limits.
        
        Returns:
            (True, None) if within limits
            (False, error_message) if exceeded
        """
        async with self._lock:
            current_time = time.time()
            
            # Initialize user entry if not exists
            if user_id not in self.user_usage:
                self.user_usage[user_id] = {
                    "rpm_count": 0,
                    "tpm_count": 0,
                    "window_start": current_time
                }
            
            usage = self.user_usage[user_id]
            elapsed = current_time - usage["window_start"]
            
            # Reset window if elapsed > 60 seconds
            if elapsed > 60:
                usage["rpm_count"] = 0
                usage["tpm_count"] = 0
                usage["window_start"] = current_time
            
            # Check RPM limit
            if usage["rpm_count"] >= self.max_rpm_per_user:
                wait_time = 60 - elapsed
                return (False, f"Per-user rate limit exceeded. Try again in {wait_time:.1f}s")
            
            # Check TPM limit
            if usage["tpm_count"] + estimated_tokens > self.max_tpm_per_user:
                wait_time = 60 - elapsed
                return (False, f"Per-user token limit exceeded. Try again in {wait_time:.1f}s")
            
            return (True, None)

    async def record_usage(self, user_id: str, tokens_used: int) -> None:
        """Record usage after a successful request."""
        async with self._lock:
            if user_id in self.user_usage:
                self.user_usage[user_id]["rpm_count"] += 1
                self.user_usage[user_id]["tpm_count"] += tokens_used


class GlobalGroqRateLimiter:
    """Tracks global Groq rate limits per model."""
    
    def __init__(self, limits: dict[str, dict]):
        self.limits = limits
        self.usage: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        
        # Initialize usage tracking for each model
        for model in limits:
            self.usage[model] = {
                "rpm_count": 0,
                "tpm_count": 0,
                "window_start": time.time()
            }

    async def check(self, model: str, estimated_tokens: int) -> tuple[bool, str | None]:
        """
        Check if model is within global Groq rate limits.
        
        Returns:
            (True, None) if within limits
            (False, error_message) if exceeded
        """
        if model not in self.limits:
            return (False, f"Unknown model: {model}")
        
        async with self._lock:
            current_time = time.time()
            usage = self.usage[model]
            limits = self.limits[model]
            elapsed = current_time - usage["window_start"]
            
            # Reset window if elapsed > 60 seconds
            if elapsed > 60:
                usage["rpm_count"] = 0
                usage["tpm_count"] = 0
                usage["window_start"] = current_time
            
            # Check RPM limit
            if usage["rpm_count"] >= limits["rpm"]:
                return (False, f"Groq {model} RPM limit reached")
            
            # Check TPM limit
            if usage["tpm_count"] + estimated_tokens > limits["tpm"]:
                return (False, f"Groq {model} TPM limit reached")
            
            return (True, None)

    async def record_usage(self, model: str, tokens_used: int) -> None:
        """Record usage after a successful Groq request."""
        async with self._lock:
            if model in self.usage:
                self.usage[model]["rpm_count"] += 1
                self.usage[model]["tpm_count"] += tokens_used


class LLMRouter:
    """
    Routes LLM requests to appropriate provider and model.
    
    Groq is primary (fast inference), Gemini is fallback (when rate-limited).
    """
    
    GROQ_LIMITS = {
        "llama-3.1-8b-instant": {"rpm": 30, "tpm": 131072},
        "llama-3.3-70b-versatile": {"rpm": 30, "tpm": 131072},
    }
    
    # Task types that have fallback support
    FALLBACK_SUPPORTED = {"orchestrate", "task", "complex"}

    def __init__(self, groq_client: GroqClient | None = None,
                 gemini_client: GeminiClient | None = None,
                 max_rpm_per_user: int = 10, max_tpm_per_user: int = 50000):
        if groq_client is None:
            try:
                groq_client = GroqClient()
            except Exception as exc:
                logger.warning("Groq client unavailable at startup: %s", exc)

        if gemini_client is None:
            try:
                gemini_client = GeminiClient()
            except Exception as exc:
                logger.warning("Gemini client unavailable at startup: %s", exc)

        self.groq_client = groq_client
        self.gemini_client = gemini_client
        self.per_user_limiter = PerUserRateLimiter(max_rpm_per_user, max_tpm_per_user)
        self.groq_limiter = GlobalGroqRateLimiter(self.GROQ_LIMITS)
        self._lock = asyncio.Lock()

    def _estimate_tokens(self, messages: list[dict]) -> int:
        """
        Estimate token count from messages.
        
        Uses rough heuristic: ~4 characters per token for English text.
        """
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                # Handle multi-part content (e.g., with images)
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        total_chars += len(part["text"])
        
        # Rough estimate: 4 chars per token, with 10% buffer
        estimated = int((total_chars / 4) * 1.1)
        return max(estimated, 10)  # Minimum 10 tokens

    def _select_groq_model(self, task_type: str) -> str:
        """Select appropriate Groq model based on task type."""
        if task_type in ("orchestrate", "memory", "search"):
            return "llama-3.1-8b-instant"
        elif task_type in ("task", "complex"):
            return "llama-3.3-70b-versatile"
        else:
            # Default to fast model for unknown task types
            return "llama-3.1-8b-instant"

    def _select_gemini_model(self, task_type: str) -> str:
        """Select appropriate Gemini model based on task type."""
        if task_type == "complex":
            return "gemini-1.5-pro"
        else:
            return "gemini-2.0-flash"

    async def route(self, user_id: str, task_type: str,
                    estimated_tokens: int) -> tuple[str, str] | tuple[None, str]:
        """
        Determine which provider and model to use.
        
        Args:
            user_id: Unique identifier for the user
            task_type: Type of task (orchestrate, task, memory, search, complex)
            estimated_tokens: Estimated token count for the request
            
        Returns:
            (provider, model) tuple on success
            (None, error_message) tuple on failure
        """
        async with self._lock:
            # Step 1: Check per-user rate limit
            user_ok, user_error = await self.per_user_limiter.check(user_id, estimated_tokens)
            if not user_ok:
                return (None, user_error)
            
            # Step 2: Select Groq model based on task type
            groq_model = self._select_groq_model(task_type)
            
            # Step 3: Check global Groq rate limit for the selected model
            groq_ok, groq_error = await self.groq_limiter.check(groq_model, estimated_tokens)
            
            # Step 4: If within Groq limits, use Groq
            if groq_ok:
                return ("groq", groq_model)
            
            # Step 5: If Groq rate-limited, check if fallback is supported
            if task_type in self.FALLBACK_SUPPORTED:
                gemini_model = self._select_gemini_model(task_type)
                return ("gemini", gemini_model)
            
            # No fallback available for this task type (memory, search)
            return (None, f"Groq rate limited and no fallback for task type '{task_type}': {groq_error}")

    async def call(self, user_id: str, task_type: str, messages: list[dict],
                   stream: bool = False, max_tokens: int = 1000) -> str | AsyncIterator[str]:
        """
        High-level call: routes and executes LLM request.
        
        Args:
            user_id: Unique identifier for the user
            task_type: Type of task (orchestrate, task, memory, search, complex)
            messages: List of message dicts with 'role' and 'content'
            stream: Whether to stream the response
            max_tokens: Maximum tokens in response
            
        Returns:
            Response text (str) or async iterator of chunks (if streaming)
            
        Raises:
            RuntimeError: If routing fails or LLM call fails
        """
        # Step 1: Estimate tokens from messages
        estimated_tokens = self._estimate_tokens(messages)
        
        # Step 2: Route to appropriate provider/model
        provider, model_or_error = await self.route(user_id, task_type, estimated_tokens)
        
        if provider is None:
            raise RuntimeError(f"LLM routing failed: {model_or_error}")
        
        model = model_or_error
        
        # Step 3 & 4: Call the appropriate client
        try:
            if provider == "groq":
                if self.groq_client is None:
                    if self.gemini_client is not None and task_type in self.FALLBACK_SUPPORTED:
                        provider = "gemini"
                        model = self._select_gemini_model(task_type)
                    else:
                        raise RuntimeError("Groq client not configured (missing GROQ_API_KEY)")
                if stream:
                    response = self._stream_groq(user_id, model, messages, max_tokens, estimated_tokens)
                else:
                    response = await self._call_groq(user_id, model, messages, max_tokens, estimated_tokens)
            else:  # provider == "gemini"
                if self.gemini_client is None:
                    raise RuntimeError("Gemini client not configured (missing GEMINI_API_KEY)")
                if stream:
                    response = self._stream_gemini(user_id, model, messages, max_tokens, estimated_tokens)
                else:
                    response = await self._call_gemini(user_id, model, messages, max_tokens, estimated_tokens)
            
            return response
            
        except Exception as e:
            # If Groq fails, try fallback to Gemini if supported
            if provider == "groq" and task_type in self.FALLBACK_SUPPORTED:
                gemini_model = self._select_gemini_model(task_type)
                try:
                    if stream:
                        return self._stream_gemini(user_id, gemini_model, messages, max_tokens, estimated_tokens)
                    else:
                        return await self._call_gemini(user_id, gemini_model, messages, max_tokens, estimated_tokens)
                except Exception as fallback_error:
                    raise RuntimeError(f"Both Groq and Gemini failed: {e}, {fallback_error}")
            raise RuntimeError(f"LLM call failed: {e}")

    async def _call_groq(self, user_id: str, model: str, messages: list[dict],
                         max_tokens: int, estimated_tokens: int) -> str:
        """Execute non-streaming Groq call and record usage."""
        response = await self.groq_client.chat(
            model=model,
            messages=messages,
            stream=False,
            max_tokens=max_tokens
        )
        
        # Record usage (estimate response tokens from response length)
        response_tokens = len(response) // 4 if response else 0
        total_tokens = estimated_tokens + response_tokens
        
        await self.groq_limiter.record_usage(model, total_tokens)
        await self.per_user_limiter.record_usage(user_id, total_tokens)
        
        return response

    async def _stream_groq(self, user_id: str, model: str, messages: list[dict],
                           max_tokens: int, estimated_tokens: int) -> AsyncIterator[str]:
        """Execute streaming Groq call and record usage."""
        total_response_chars = 0
        
        async for chunk in self.groq_client.chat(
            model=model,
            messages=messages,
            stream=True,
            max_tokens=max_tokens
        ):
            total_response_chars += len(chunk)
            yield chunk
        
        # Record usage after streaming completes
        response_tokens = total_response_chars // 4
        total_tokens = estimated_tokens + response_tokens
        
        await self.groq_limiter.record_usage(model, total_tokens)
        await self.per_user_limiter.record_usage(user_id, total_tokens)

    async def _call_gemini(self, user_id: str, model: str, messages: list[dict],
                           max_tokens: int, estimated_tokens: int) -> str:
        """Execute non-streaming Gemini call and record usage."""
        response = await self.gemini_client.chat(
            model=model,
            messages=messages,
            stream=False,
            max_tokens=max_tokens
        )
        
        # Record per-user usage (Gemini doesn't have global limits we track)
        response_tokens = len(response) // 4 if response else 0
        total_tokens = estimated_tokens + response_tokens
        
        await self.per_user_limiter.record_usage(user_id, total_tokens)
        
        return response

    async def _stream_gemini(self, user_id: str, model: str, messages: list[dict],
                             max_tokens: int, estimated_tokens: int) -> AsyncIterator[str]:
        """Execute streaming Gemini call and record usage."""
        total_response_chars = 0
        
        async for chunk in self.gemini_client.chat(
            model=model,
            messages=messages,
            stream=True,
            max_tokens=max_tokens
        ):
            total_response_chars += len(chunk)
            yield chunk
        
        # Record usage after streaming completes
        response_tokens = total_response_chars // 4
        total_tokens = estimated_tokens + response_tokens
        
        await self.per_user_limiter.record_usage(user_id, total_tokens)

    async def get_usage_stats(self, user_id: str | None = None) -> dict:
        """Get current usage statistics for debugging/monitoring."""
        stats = {
            "groq_models": {},
            "timestamp": time.time()
        }
        
        # Global Groq usage
        for model, usage in self.groq_limiter.usage.items():
            limits = self.groq_limiter.limits[model]
            stats["groq_models"][model] = {
                "rpm_used": usage["rpm_count"],
                "rpm_limit": limits["rpm"],
                "tpm_used": usage["tpm_count"],
                "tpm_limit": limits["tpm"],
                "window_age_seconds": time.time() - usage["window_start"]
            }
        
        # Per-user usage if requested
        if user_id and user_id in self.per_user_limiter.user_usage:
            user_usage = self.per_user_limiter.user_usage[user_id]
            stats["user"] = {
                "user_id": user_id,
                "rpm_used": user_usage["rpm_count"],
                "rpm_limit": self.per_user_limiter.max_rpm_per_user,
                "tpm_used": user_usage["tpm_count"],
                "tpm_limit": self.per_user_limiter.max_tpm_per_user,
                "window_age_seconds": time.time() - user_usage["window_start"]
            }
        
        return stats