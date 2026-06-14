from __future__ import annotations

from collections.abc import AsyncIterator

from server.voice.stt.base import STTBackend
from server.voice.transcript import is_meaningful_transcript, voice_pcm_is_viable
from server.voice.types import TranscriptEvent


async def transcribe_pcm_chunks(stt: STTBackend, pcm_chunks: list[bytes]) -> str | None:
    """Run STT on buffered PCM chunks; return transcript or None if unusable."""
    if not voice_pcm_is_viable(pcm_chunks):
        return None

    async def chunk_iter() -> AsyncIterator[bytes]:
        for chunk in pcm_chunks:
            yield chunk

    transcript = ""
    async for event in stt.transcribe_stream(chunk_iter()):
        if isinstance(event, TranscriptEvent):
            transcript = event.text

    transcript = transcript.strip()
    if not is_meaningful_transcript(transcript):
        return None
    return transcript
