from __future__ import annotations

import re

SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+|(?<=—)\s+|(?<=\.\.\.)\s+")


def drain_complete_sentences(buffer: str) -> tuple[list[str], str]:
    """
    Split buffer on sentence boundaries. Returns finished sentences and the
    remainder (incomplete tail kept for more tokens).
    """
    if not buffer:
        return [], ""

    parts = SENTENCE_BOUNDARY_RE.split(buffer)
    if len(parts) == 1:
        return [], buffer

    complete = [part.strip() for part in parts[:-1] if part.strip()]
    return complete, parts[-1]
