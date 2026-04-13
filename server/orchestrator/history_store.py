from __future__ import annotations

from dataclasses import dataclass

COMPRESSION_TRIGGER = 20_000
KEEP_RECENT_TURNS = 6


@dataclass
class TurnMessage:
    role: str
    text: str


class HistoryStore:
    def __init__(self):
        self._turns: dict[str, list[dict]] = {}

    def get(self, session_id: str) -> list[dict]:
        return list(self._turns.get(session_id, []))

    def set(self, session_id: str, turns: list[dict]) -> None:
        self._turns[session_id] = list(turns)

    def clear(self, session_id: str) -> None:
        self._turns.pop(session_id, None)

    def append(self, session_id: str, user_text: str, assistant_text: str) -> None:
        turns = self._turns.setdefault(session_id, [])
        turns.append({"role": "user", "content": [{"type": "text", "text": user_text}]})
        turns.append({"role": "assistant", "content": [{"type": "text", "text": assistant_text}]})

    def estimate_tokens(self, session_id: str) -> int:
        turns = self._turns.get(session_id, [])
        chars = 0
        for item in turns:
            for chunk in item.get("content", []):
                chars += len(str(chunk.get("text", "")))
        return chars // 4

    def maybe_compress(self, session_id: str) -> list[dict]:
        turns = self._turns.get(session_id, [])
        if not turns:
            return []

        if self.estimate_tokens(session_id) < COMPRESSION_TRIGGER:
            return []

        keep_n = KEEP_RECENT_TURNS * 2
        to_compress = turns[:-keep_n] if len(turns) > keep_n else []
        recent = turns[-keep_n:] if keep_n <= len(turns) else turns

        if not to_compress:
            return []

        summary_lines = []
        for item in to_compress[-10:]:
            role = item.get("role", "user")
            text = ""
            for chunk in item.get("content", []):
                if isinstance(chunk, dict) and chunk.get("type") == "text":
                    text += str(chunk.get("text", ""))
            if text:
                summary_lines.append(f"{role}: {text[:140]}")

        summary = " ".join(summary_lines)[:1200]
        self._turns[session_id] = [
            {
                "role": "system",
                "content": [{"type": "text", "text": f"[EARLIER CONVERSATION SUMMARY]\n{summary}"}],
            }
        ] + recent

        return to_compress


history_store = HistoryStore()
