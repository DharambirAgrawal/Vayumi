from __future__ import annotations

import re

# ~0.3s of 16 kHz mono PCM s16le
MIN_VOICE_PCM_BYTES = 9_600

_JUNK_TRANSCRIPT_RE = re.compile(r"^[\s.,!?…\-–—'\"`]+$")


def voice_pcm_byte_count(chunks: list[bytes]) -> int:
    return sum(len(c) for c in chunks)


def voice_pcm_is_viable(chunks: list[bytes]) -> bool:
    return voice_pcm_byte_count(chunks) >= MIN_VOICE_PCM_BYTES


def is_meaningful_transcript(text: str) -> bool:
    """Drop silence, punctuation-only, and other STT noise."""
    cleaned = text.strip()
    if not cleaned:
        return False
    if _JUNK_TRANSCRIPT_RE.match(cleaned):
        return False
    if len(cleaned) < 2:
        return False
    return True
