from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List


@dataclass
class Turn:
    speaker_id: str
    text: str
    timestamp: datetime


class ShortTermBuffer:
    """In-session sliding window with a simple approximate token budget."""

    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens
        self._turns: List[Turn] = []

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        # Approximation: 1 token ~= 4 characters for English-like text.
        return max(1, len(text) // 4)

    def add(self, speaker_id: str, text: str) -> None:
        self._turns.append(Turn(speaker_id=speaker_id, text=text, timestamp=datetime.utcnow()))
        while self.token_count() > self.max_tokens and self._turns:
            self._turns.pop(0)

    def get_context(self) -> str:
        if not self._turns:
            return ""
        start = self._turns[0].timestamp
        lines: List[str] = []
        for turn in self._turns:
            elapsed = int((turn.timestamp - start).total_seconds())
            hh = elapsed // 3600
            mm = (elapsed % 3600) // 60
            ss = elapsed % 60
            lines.append(f"[{turn.speaker_id} {hh:01d}:{mm:02d}:{ss:02d}] {turn.text}")
        return "\n".join(lines)

    def get_turns(self) -> List[Turn]:
        return list(self._turns)

    def token_count(self) -> int:
        return sum(self._estimate_tokens(t.text) for t in self._turns)

    def clear(self) -> None:
        self._turns.clear()

    def to_text(self) -> str:
        return "\n".join(f"{turn.speaker_id}: {turn.text}" for turn in self._turns)
