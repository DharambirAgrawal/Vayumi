from __future__ import annotations

import re
from difflib import SequenceMatcher

from server.orchestrator.directives import strip_internal_tool_blocks

_STALE_PROMISE_RE = re.compile(
    r"still working|let you know when|i'll let you know|i will let you know|"
    r"when that'?s done|when i have the full|pull in all the relevant|"
    r"read them thoroughly",
    re.IGNORECASE,
)


def sanitize_spoken_prose(text: str) -> str:
    """Remove raw URLs and markdown links so voice/chat sounds human."""
    out = text.strip()
    out = re.sub(r"^```+\s*", "", out)
    out = re.sub(r"\s*```+\s*$", "", out)
    out = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", out)
    out = re.sub(r"\[https?://[^\]]+\]", "", out)
    out = re.sub(r"https?://\S+", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def scrub_follow_up_prose(text: str, *, spoken_ack: str = "") -> str:
    """Remove directive junk and repeated plan ack from the answer pass."""
    stripped = strip_internal_tool_blocks(text.strip())
    if not stripped:
        return ""
    ack_lower = spoken_ack.strip().lower()
    kept: list[str] = []
    for line in stripped.splitlines():
        chunk = line.strip()
        if not chunk or chunk in ("!", "]", "[", "!"):
            continue
        if chunk.startswith("]"):
            chunk = chunk.lstrip("]").strip()
            if not chunk:
                continue
        chunk_lower = chunk.lower()
        if ack_lower and chunk_lower == ack_lower:
            continue
        if ack_lower and chunk_lower.startswith(ack_lower) and len(chunk) <= len(spoken_ack) + 4:
            continue
        if _STALE_PROMISE_RE.search(chunk):
            continue
        kept.append(chunk)
    return sanitize_spoken_prose("\n".join(kept))


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
            return sanitize_spoken_prose(head)

    return sanitize_spoken_prose(stripped)


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
