# # =============================================================================
# # server/voice/stt.py — Groq Whisper STT Wrapper
# # =============================================================================
# #
# # PURPOSE:
# #   Wraps the Groq Whisper API for speech-to-text transcription.
# #   Receives raw audio bytes (16kHz 16-bit mono PCM or WAV), sends to Groq
# #   Whisper endpoint, returns transcribed text.
# #
# # API DETAILS:
# #   Provider: Groq Cloud
# #   Model: whisper-large-v3 (or latest available Whisper model on Groq)
# #   Input: Audio bytes (WAV or raw PCM format)
# #   Output: Transcribed text string
# #   Latency: ~200-500ms for typical utterances (Groq is fast)
# #   Languages: Multi-language support (default: en)
# #
# # CLASS: STTEngine
# #
# #   __init__(self, api_key: str | None = None):
# #     - api_key loaded from env var GROQ_API_KEY if not provided
# #     - Initializes AsyncGroq client
# #
# #   async transcribe(self, audio_bytes: bytes, language: str = "en") -> str:
# #     Transcribes audio to text.
# #     Steps:
# #       1. Wrap audio_bytes as a file-like object (io.BytesIO)
# #       2. Call Groq Whisper API:
# #          client.audio.transcriptions.create(
# #            model="whisper-large-v3",
# #            file=("audio.wav", audio_buffer, "audio/wav"),
# #            language=language
# #          )
# #       3. Return transcription.text
# #     Error handling:
# #       - Timeout → return "" (empty string, handler sends "I didn't catch that")
# #       - API error → log error, return ""
# #
# # USAGE:
# #   Called by ws/handler.py handle_audio_chunk after VAD confirms speech.
# #   Also called by interrupt_handler.handle_speech_interrupt for interrupt transcription.
# #
# # IMPORTS NEEDED:
# # =============================================================================

# import os
# import io

# from groq import AsyncGroq


# class STTEngine:
#     def __init__(self, api_key: str | None = None):
#         self.api_key = api_key or os.getenv("GROQ_API_KEY")
#         self.client = AsyncGroq(api_key=self.api_key)
#         self.model = "whisper-large-v3"

#     async def transcribe(self, audio_bytes: bytes, language: str = "en") -> str:
#         pass

# =============================================================================
# server/voice/stt.py — Groq Whisper STT Wrapper
# =============================================================================

import io
import logging
import os

from groq import AsyncGroq

logger = logging.getLogger(__name__)


class STTEngine:
    """
    Wraps the Groq Whisper API for speech-to-text transcription.

    Receives raw audio bytes (16 kHz 16-bit mono PCM or WAV), sends to the
    Groq Whisper endpoint, and returns the transcribed text.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key: str = api_key or os.getenv("GROQ_API_KEY", "")
        if not self.api_key:
            logger.warning(
                "GROQ_API_KEY is not set — STT transcription calls will fail."
            )
        self.client: AsyncGroq = AsyncGroq(api_key=self.api_key)
        self.model: str = "whisper-large-v3"

    async def transcribe(self, audio_bytes: bytes, language: str = "en") -> str:
        """
        Transcribe *audio_bytes* to text via the Groq Whisper API.

        Parameters
        ----------
        audio_bytes:
            Raw 16 kHz / 16-bit mono PCM **or** a complete WAV file.
        language:
            BCP-47 language hint (default ``"en"``).

        Returns
        -------
        str
            The transcribed text, or ``""`` on any failure (timeout,
            API error, empty audio, etc.).
        """
        if not audio_bytes:
            return ""

        audio_buffer = io.BytesIO(audio_bytes)

        try:
            transcription = await self.client.audio.transcriptions.create(
                model=self.model,
                file=("audio.wav", audio_buffer, "audio/wav"),
                language=language,
            )
            text = (transcription.text or "").strip()
            logger.debug("STT result (%d audio bytes): %s", len(audio_bytes), text)
            return text

        except TimeoutError:
            logger.warning("Groq Whisper request timed out.")
            return ""

        except Exception as exc:
            logger.error("Groq Whisper API error: %s", exc, exc_info=True)
            return ""