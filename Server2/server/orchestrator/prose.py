from __future__ import annotations

import re
from difflib import SequenceMatcher

from server.orchestrator.directives import strip_internal_tool_blocks

_TAVILY_META_RE = re.compile(r"\d+\s+result\(s\)\s+from\s+tavily", re.IGNORECASE)
_TOOL_SEARCH_META_RE = re.compile(r"Found\s+\d+\s+tool\(s\)\s+for\s+", re.IGNORECASE)
_SNIPPET_LINE_RE = re.compile(r"^\d+\.\s+.+\s+—\s+")
_FOLLOW_UP_INSTRUCTION_RE = re.compile(
    r"^(?:Today is \d{4}-\d{2}-\d{2}\.|Answer from the immediate|Snippet numbers are|"
    r"User's latest message \(answer ONLY|=== Tool snippets|=== Answer now|"
    r"--- Immediate result \d+:|Never quote snippet numbers)",
    re.IGNORECASE,
)
_STALE_PROMISE_RE = re.compile(
    r"still working|let you know when|i'll let you know|i will let you know|"
    r"when that'?s done|when i have the full|pull in all the relevant|"
    r"read them thoroughly",
    re.IGNORECASE,
)


def strip_tool_artifacts(text: str) -> str:
    """Remove echoed tool summaries, snippet dumps, and follow-up instructions."""
    if not text.strip():
        return ""
    kept: list[str] = []
    for line in text.splitlines():
        chunk = line.strip()
        if not chunk:
            continue
        chunk = _TAVILY_META_RE.sub("", chunk).strip()
        chunk = _TOOL_SEARCH_META_RE.sub("", chunk).strip()
        if not chunk:
            continue
        if _SNIPPET_LINE_RE.match(chunk):
            continue
        if _FOLLOW_UP_INSTRUCTION_RE.match(chunk):
            continue
        if chunk.startswith("[TOOL_RESULT"):
            continue
        kept.append(chunk)
    out = "\n".join(kept)
    out = _TAVILY_META_RE.sub("", out)
    out = _TOOL_SEARCH_META_RE.sub("", out)
    return re.sub(r"\s+", " ", out).strip()


def sanitize_spoken_prose(text: str) -> str:
    """Remove raw URLs and markdown links so voice/chat sounds human."""
    out = strip_tool_artifacts(text.strip())
    out = re.sub(r"^```+\s*", "", out)
    out = re.sub(r"\s*```+\s*$", "", out)
    out = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", out)
    out = re.sub(r"\[https?://[^\]]+\]", "", out)
    out = re.sub(r"https?://\S+", "", out)
    # Strip accidental tool payload leakage (when model forgets [DELEGATE])
    out = re.sub(r"payload=\{.*", "", out, flags=re.DOTALL)
    out = re.sub(r"\[web_search[^\]]*\]", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\*\*([^*]+)\*\*", r"\1", out)
    out = re.sub(r"(?:^|\n)\s*\*\s+", " ", out)
    out = re.sub(r"\s+\*\s+", " ", out)
    out = re.sub(r"\s+([,.!?;:])", r"\1", out)
    out = re.sub(r"\.!+", ".", out)
    out = re.sub(r"([.!?])\1+", r"\1", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def scrub_follow_up_prose(text: str, *, spoken_ack: str = "") -> str:
    """Remove directive junk and repeated plan ack from the answer pass."""
    stripped = strip_tool_artifacts(strip_internal_tool_blocks(text.strip()))
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
