from __future__ import annotations

import re
from difflib import SequenceMatcher

from server.orchestrator.directives import strip_internal_tool_blocks


def finalize_assistant_prose(text: str) -> str:
    """
    Collapse redundant trailing blocks when the model repeats the same answer
    (often wrapped in markdown). Uses content similarity, not symbol stripping.
    """
    stripped = strip_internal_tool_blocks(text.strip())
    if not stripped:
        return ""

    for match in re.finditer(r"\n\s*\n", stripped):
        head = stripped[: match.start()].strip()
        tail = stripped[match.end() :].strip()
        if head and tail and texts_largely_repeat(head, tail):
            return head

    return stripped


def texts_largely_repeat(earlier: str, later: str) -> bool:
    if not later.strip():
        return False
    if later.strip() in earlier:
        return True
    if earlier.strip() in later:
        return True

    a = _word_tokens(earlier)
    b = _word_tokens(later)
    if not b:
        return False

    overlap = len(a & b) / len(b)
    if overlap >= 0.75:
        return True

    a_joined = " ".join(sorted(a))
    b_joined = " ".join(sorted(b))
    return SequenceMatcher(None, a_joined, b_joined).ratio() >= 0.78


def _word_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) > 1}
