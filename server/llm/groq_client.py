# =============================================================================
# server/llm/groq_client.py — Groq API Wrapper
# =============================================================================

import os
from typing import AsyncIterator

from groq import AsyncGroq, APIError, RateLimitError, APITimeoutError, APIConnectionError


class GroqClientError(Exception):
    """Base exception for Groq client errors."""
    pass


class GroqRateLimitError(GroqClientError):
    """Raised when Groq API returns 429 rate limit error."""
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class GroqTimeoutError(GroqClientError):
    """Raised when Groq API request times out."""
    pass


class GroqClient:
    """
    Async wrapper for the Groq API.
    
    Groq is the PRIMARY provider for most tasks due to extremely fast
    inference (low latency), critical for natural conversational flow.
    
    Models used:
        - llama-3.1-8b-instant: Fast routing, orchestration, memory, search
        - llama-3.3-70b-versatile: Task execution, multi-step reasoning
    """
    
    DEFAULT_TIMEOUT = 30.0  # seconds
    
    def __init__(self, api_key: str | None = None, timeout: float | None = None):
        """
        Initialize the Groq client.
        
        Args:
            api_key: Groq API key. If None, reads from GROQ_API_KEY env var.
            timeout: Request timeout in seconds. Defaults to 30s.
        
        Raises:
            ValueError: If no API key is provided or found in environment.
        """
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        
        if not self.api_key:
            raise ValueError(
                "Groq API key is required. Provide via constructor or "
                "set GROQ_API_KEY environment variable."
            )
        
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.client = AsyncGroq(
            api_key=self.api_key,
            timeout=self.timeout
        )

    async def chat(
        self,
        model: str,
        messages: list[dict],
        stream: bool = False,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        top_p: float = 1.0,
        stop: list[str] | None = None
    ) -> str | AsyncIterator[str]:
        """
        Make a chat completion call to Groq API.
        
        Args:
            model: Groq model name (e.g., "llama-3.1-8b-instant")
            messages: List of message dicts with 'role' and 'content' keys
            stream: If True, returns an async iterator yielding tokens
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (0.0 to 2.0)
            top_p: Nucleus sampling parameter
            stop: Optional list of stop sequences
            
        Returns:
            If stream=False: Complete response text as string
            If stream=True: Async iterator yielding response chunks
            
        Raises:
            GroqRateLimitError: When rate limited (429) - allows router to fallback
            GroqTimeoutError: When request times out
            GroqClientError: For other API errors
        """
        try:
            if stream:
                return self._stream_chat(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    stop=stop
                )
            else:
                return await self._complete_chat(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    stop=stop
                )
                
        except RateLimitError as e:
            # Extract retry-after header if available
            retry_after = None
            if hasattr(e, 'response') and e.response is not None:
                retry_after_header = e.response.headers.get('retry-after')
                if retry_after_header:
                    try:
                        retry_after = float(retry_after_header)
                    except ValueError:
                        pass
            
            raise GroqRateLimitError(
                f"Groq rate limit exceeded for model {model}: {str(e)}",
                retry_after=retry_after
            ) from e
            
        except APITimeoutError as e:
            raise GroqTimeoutError(
                f"Groq request timed out after {self.timeout}s: {str(e)}"
            ) from e
            
        except APIConnectionError as e:
            raise GroqClientError(
                f"Failed to connect to Groq API: {str(e)}"
            ) from e
            
        except APIError as e:
            raise GroqClientError(
                f"Groq API error (status {e.status_code}): {str(e)}"
            ) from e
            
        except Exception as e:
            raise GroqClientError(
                f"Unexpected error calling Groq API: {str(e)}"
            ) from e

    async def _complete_chat(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        top_p: float,
        stop: list[str] | None
    ) -> str:
        """Execute non-streaming chat completion."""
        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=stop,
            stream=False
        )
        
        # Extract content from response
        if not response.choices:
            raise GroqClientError("Groq returned empty response with no choices")
        
        content = response.choices[0].message.content
        
        if content is None:
            # Handle case where model returns empty content
            return ""
        
        return content

    async def _stream_chat(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        top_p: float,
        stop: list[str] | None
    ) -> AsyncIterator[str]:
        """
        Execute streaming chat completion.
        
        Yields response tokens as they arrive.
        """
        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=stop,
            stream=True
        )
        
        async for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content

    async def health_check(self) -> bool:
        """
        Check if Groq API is accessible.
        
        Returns:
            True if API is accessible, False otherwise.
        """
        try:
            # Make a minimal request to verify connectivity
            await self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1
            )
            return True
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """
        List available models from Groq.
        
        Returns:
            List of model IDs available for use.
        """
        try:
            models = await self.client.models.list()
            return [model.id for model in models.data]
        except Exception as e:
            raise GroqClientError(f"Failed to list Groq models: {str(e)}") from e