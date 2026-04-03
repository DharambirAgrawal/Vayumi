# =============================================================================
# server/llm/gemini_client.py — Google Gemini API Wrapper
# =============================================================================

import os
import asyncio
from typing import AsyncIterator
from functools import partial

import google.generativeai as genai
from google.generativeai.types import (
    GenerationConfig,
    HarmCategory,
    HarmBlockThreshold,
    BlockedPromptException,
    StopCandidateException,
)
from google.api_core import exceptions as google_exceptions


class GeminiClientError(Exception):
    """Base exception for Gemini client errors."""
    pass


class GeminiSafetyError(GeminiClientError):
    """Raised when content is blocked by safety filters."""
    def __init__(self, message: str, safety_ratings: list | None = None):
        super().__init__(message)
        self.safety_ratings = safety_ratings


class GeminiTimeoutError(GeminiClientError):
    """Raised when Gemini API request times out."""
    pass


class GeminiClient:
    """
    Async wrapper for the Google Gemini API.
    
    Gemini serves as:
        1. FALLBACK when Groq is rate-limited
        2. PRIMARY for complex reasoning tasks needing stronger models
    
    Models used:
        - gemini-2.0-flash: Default fallback for most tasks (fast, capable)
        - gemini-1.5-pro: Complex reasoning tasks requiring high intelligence
    """
    
    DEFAULT_TIMEOUT = 60.0  # seconds (Gemini can be slower than Groq)
    
    # Safety settings - permissive for assistant use cases
    DEFAULT_SAFETY_SETTINGS = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
    }
    
    SAFETY_BLOCKED_RESPONSE = (
        "I'm not able to respond to that request. "
        "Could you please rephrase or ask something else?"
    )

    def __init__(self, api_key: str | None = None, timeout: float | None = None):
        """
        Initialize the Gemini client.
        
        Args:
            api_key: Gemini API key. If None, reads from GEMINI_API_KEY env var.
            timeout: Request timeout in seconds. Defaults to 60s.
        
        Raises:
            ValueError: If no API key is provided or found in environment.
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        
        if not self.api_key:
            raise ValueError(
                "Gemini API key is required. Provide via constructor or "
                "set GEMINI_API_KEY environment variable."
            )
        
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        genai.configure(api_key=self.api_key)
        
        # Cache model instances
        self._model_cache: dict[str, genai.GenerativeModel] = {}

    def _get_model(self, model_name: str) -> genai.GenerativeModel:
        """Get or create a cached model instance."""
        if model_name not in self._model_cache:
            self._model_cache[model_name] = genai.GenerativeModel(
                model_name=model_name,
                safety_settings=self.DEFAULT_SAFETY_SETTINGS
            )
        return self._model_cache[model_name]

    def _convert_messages(self, messages: list[dict]) -> tuple[list, str | None]:
        """
        Convert OpenAI-style messages to Gemini format.
        
        Gemini uses:
            - "user" for user messages
            - "model" for assistant messages
            - System message is handled separately via system_instruction
        
        Args:
            messages: List of dicts with 'role' and 'content' keys
            
        Returns:
            Tuple of (converted_messages, system_instruction)
        """
        system_instruction = None
        converted = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                # Accumulate system messages
                if system_instruction is None:
                    system_instruction = content
                else:
                    system_instruction += "\n" + content
                    
            elif role == "assistant":
                # Gemini uses "model" for assistant responses
                converted.append({
                    "role": "model",
                    "parts": [content]
                })
                
            elif role == "user":
                converted.append({
                    "role": "user",
                    "parts": [content]
                })
                
            else:
                # Unknown role, treat as user
                converted.append({
                    "role": "user", 
                    "parts": [f"[{role}]: {content}"]
                })
        
        # If no messages after conversion, add a placeholder
        if not converted:
            converted.append({
                "role": "user",
                "parts": ["Hello"]
            })
        
        return converted, system_instruction

    async def chat(
        self,
        model: str,
        messages: list[dict],
        stream: bool = False,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        top_p: float = 0.95,
        top_k: int = 40,
        stop_sequences: list[str] | None = None
    ) -> str | AsyncIterator[str]:
        """
        Make a chat completion call to Gemini API.
        
        Args:
            model: Gemini model name (e.g., "gemini-2.0-flash")
            messages: List of message dicts with 'role' and 'content' keys
            stream: If True, returns an async iterator yielding tokens
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (0.0 to 2.0)
            top_p: Nucleus sampling parameter
            top_k: Top-k sampling parameter
            stop_sequences: Optional list of stop sequences
            
        Returns:
            If stream=False: Complete response text as string
            If stream=True: Async iterator yielding response chunks
            
        Raises:
            GeminiSafetyError: When content is blocked by safety filters
            GeminiTimeoutError: When request times out
            GeminiClientError: For other API errors
        """
        try:
            # Convert messages to Gemini format
            contents, system_instruction = self._convert_messages(messages)
            
            # Create generation config
            generation_config = GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                stop_sequences=stop_sequences or []
            )
            
            # Get model (with system instruction if provided)
            if system_instruction:
                model_obj = genai.GenerativeModel(
                    model_name=model,
                    safety_settings=self.DEFAULT_SAFETY_SETTINGS,
                    system_instruction=system_instruction
                )
            else:
                model_obj = self._get_model(model)
            
            if stream:
                return self._stream_chat(model_obj, contents, generation_config)
            else:
                return await self._complete_chat(model_obj, contents, generation_config)
                
        except BlockedPromptException as e:
            # Input was blocked by safety filters
            raise GeminiSafetyError(
                "Prompt blocked by Gemini safety filters",
                safety_ratings=getattr(e, 'safety_ratings', None)
            ) from e
            
        except StopCandidateException as e:
            # Response was stopped due to safety
            raise GeminiSafetyError(
                "Response stopped by Gemini safety filters",
                safety_ratings=getattr(e, 'safety_ratings', None)
            ) from e
            
        except google_exceptions.DeadlineExceeded as e:
            raise GeminiTimeoutError(
                f"Gemini request timed out: {str(e)}"
            ) from e
            
        except google_exceptions.ResourceExhausted as e:
            raise GeminiClientError(
                f"Gemini quota exceeded: {str(e)}"
            ) from e
            
        except google_exceptions.InvalidArgument as e:
            raise GeminiClientError(
                f"Invalid request to Gemini: {str(e)}"
            ) from e
            
        except google_exceptions.GoogleAPIError as e:
            raise GeminiClientError(
                f"Gemini API error: {str(e)}"
            ) from e
            
        except Exception as e:
            raise GeminiClientError(
                f"Unexpected error calling Gemini API: {str(e)}"
            ) from e

    async def _complete_chat(
        self,
        model_obj: genai.GenerativeModel,
        contents: list,
        generation_config: GenerationConfig
    ) -> str:
        """Execute non-streaming chat completion."""
        # Run synchronous Gemini call in thread pool
        loop = asyncio.get_event_loop()
        
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                partial(
                    model_obj.generate_content,
                    contents=contents,
                    generation_config=generation_config,
                    stream=False
                )
            ),
            timeout=self.timeout
        )
        
        # Handle response
        try:
            # Check if response was blocked
            if not response.candidates:
                # Check prompt feedback for blocking reason
                if hasattr(response, 'prompt_feedback'):
                    feedback = response.prompt_feedback
                    if hasattr(feedback, 'block_reason') and feedback.block_reason:
                        return self.SAFETY_BLOCKED_RESPONSE
                return ""
            
            candidate = response.candidates[0]
            
            # Check finish reason
            if hasattr(candidate, 'finish_reason'):
                # SAFETY = 3 in the enum
                if candidate.finish_reason == 3:  # SAFETY
                    return self.SAFETY_BLOCKED_RESPONSE
            
            # Extract text
            if hasattr(response, 'text'):
                return response.text
            elif candidate.content and candidate.content.parts:
                return "".join(part.text for part in candidate.content.parts if hasattr(part, 'text'))
            else:
                return ""
                
        except ValueError as e:
            # Sometimes response.text raises ValueError for blocked content
            if "blocked" in str(e).lower() or "safety" in str(e).lower():
                return self.SAFETY_BLOCKED_RESPONSE
            raise GeminiClientError(f"Failed to extract response text: {e}") from e

    async def _stream_chat(
        self,
        model_obj: genai.GenerativeModel,
        contents: list,
        generation_config: GenerationConfig
    ) -> AsyncIterator[str]:
        """
        Execute streaming chat completion.
        
        Yields response tokens as they arrive.
        """
        loop = asyncio.get_event_loop()
        
        # Start the streaming response in executor
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                partial(
                    model_obj.generate_content,
                    contents=contents,
                    generation_config=generation_config,
                    stream=True
                )
            ),
            timeout=self.timeout
        )
        
        # Iterate over chunks
        # Note: We need to handle the sync iterator in an async context
        def get_chunks():
            chunks = []
            try:
                for chunk in response:
                    if chunk.text:
                        chunks.append(chunk.text)
            except ValueError as e:
                if "blocked" in str(e).lower() or "safety" in str(e).lower():
                    chunks.append(self.SAFETY_BLOCKED_RESPONSE)
                else:
                    raise
            return chunks
        
        chunks = await loop.run_in_executor(None, get_chunks)
        
        for chunk in chunks:
            yield chunk

    async def health_check(self) -> bool:
        """
        Check if Gemini API is accessible.
        
        Returns:
            True if API is accessible, False otherwise.
        """
        try:
            await self.chat(
                model="gemini-2.0-flash",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1
            )
            return True
        except Exception:
            return False

    async def count_tokens(self, model: str, messages: list[dict]) -> int:
        """
        Count tokens for the given messages.
        
        Args:
            model: Model name to use for counting
            messages: Messages to count tokens for
            
        Returns:
            Token count
        """
        try:
            contents, system_instruction = self._convert_messages(messages)
            model_obj = self._get_model(model)
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                partial(model_obj.count_tokens, contents)
            )
            
            token_count = result.total_tokens
            
            # Add system instruction tokens if present
            if system_instruction:
                sys_result = await loop.run_in_executor(
                    None,
                    partial(model_obj.count_tokens, system_instruction)
                )
                token_count += sys_result.total_tokens
            
            return token_count
            
        except Exception as e:
            raise GeminiClientError(f"Failed to count tokens: {e}") from e