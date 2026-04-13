from __future__ import annotations

import re
from typing import Dict, List, Optional

from memory.models import MemoryType
from memory.stores.graph import GraphStore


class MemoryRouter:
    """Extracts and classifies save-worthy memories from text."""

    def __init__(self, graph_store: GraphStore):
        self.graph_store = graph_store

    def route_turn(self, text: str, speaker_id: str, context: Optional[str] = None) -> List[Dict]:
        _ = context
        if not self.should_save(text):
            return []
        content = self.resolve_entities(text.strip(), speaker_id=speaker_id)
        memory_type = self.classify(content)
        return [{"content": content, "memory_type": memory_type.value, "confidence": 0.8}]

    def route_session(self, transcript: str, speaker_id: str) -> List[Dict]:
        results: List[Dict] = []
        for raw_line in transcript.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if ":" in line:
                _, maybe_text = line.split(":", 1)
                text = maybe_text.strip()
            else:
                text = line
            results.extend(self.route_turn(text=text, speaker_id=speaker_id))
        return results

    def classify(self, text: str) -> MemoryType:
        t = text.lower()
        if any(k in t for k in ["prefer", "i like", "i love", "i dislike", "please use", "don't use"]):
            return MemoryType.PREFERENCE
        if any(k in t for k in ["meeting", "deadline", "tomorrow", "next week", "scheduled", "at "]):
            return MemoryType.EVENT
        if any(k in t for k in ["manager", "reports to", "works with", "my wife", "my husband", "my friend"]):
            return MemoryType.RELATIONSHIP
        return MemoryType.FACT

    def resolve_entities(self, text: str, speaker_id: str) -> str:
        def repl(match: re.Match) -> str:
            name = match.group(0)
            canonical = self.graph_store.resolve_alias(name=name, speaker_id=speaker_id)
            return canonical if canonical else name

        return re.sub(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b", repl, text)

    def should_save(self, text: str, confidence_threshold: float = 0.7) -> bool:
        stripped = text.strip().lower()
        if not stripped:
            return False
        if stripped in {"ok", "thanks", "thank you", "sure", "cool", "got it"}:
            return False
        words = stripped.split()
        if len(words) < 4:
            return False
        score = self._compute_save_confidence(words, stripped)
        return score >= confidence_threshold

    def _compute_save_confidence(self, words: list, text_lower: str) -> float:
        """Return a save-worthiness confidence score in [0.0, 1.0].

        Base score starts at 0.7 (matching the default threshold) for any text
        that passes the word-count gate.  Additional length and keyword bonuses
        allow callers to raise the threshold for higher-precision filtering.
        """
        base = 0.7
        length_bonus = min(0.2, (len(words) - 4) * 0.01)
        memory_keywords = {
            "prefer", "remember", "always", "never", "important",
            "meeting", "deadline", "i like", "i dislike", "my",
        }
        keyword_bonus = 0.1 if any(kw in text_lower for kw in memory_keywords) else 0.0
        return min(1.0, base + length_bonus + keyword_bonus)
