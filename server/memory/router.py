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
        _ = confidence_threshold
        stripped = text.strip().lower()
        if not stripped:
            return False
        if stripped in {"ok", "thanks", "thank you", "sure", "cool", "got it"}:
            return False
        return len(stripped.split()) >= 4
