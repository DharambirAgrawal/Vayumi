from __future__ import annotations

_TRIVIAL_CHAT = frozenset({"?", "!", "??", "???", "...", "..", "…"})


def is_trivial_chat_followup(text: str) -> bool:
    """True for '?', '!' etc. that should not replace a queued chat message."""
    stripped = text.strip()
    if not stripped:
        return True
    if stripped in _TRIVIAL_CHAT:
        return True
    return len(stripped) <= 2
