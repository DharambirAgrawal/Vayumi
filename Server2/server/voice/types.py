from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class SpeechState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


@dataclass(frozen=True)
class TranscriptEvent:
    text: str
    is_final: bool


@dataclass(frozen=True)
class PcmFrame:
    pcm: bytes
    sample_rate: int = 16000


@dataclass(frozen=True)
class VadEvent:
    kind: Literal["speech_start", "speech_end", "silence"]
    probability: float = 0.0
