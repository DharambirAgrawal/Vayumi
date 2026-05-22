from __future__ import annotations

import re

from server.logger import get_logger

log = get_logger("orchestrator.tool_intent")

# User clearly wants live / current information from the web (not LLM training data).
_WEB_INFO_RE = re.compile(
    r"(?:"
    r"\b(?:latest|current|today'?s?|recent|breaking)\s+(?:news|headlines|updates|events)"
    r"|"
    r"\b(?:news|headlines)\b"
    r"|"
    r"\bwhat(?:'s| is)\s+(?:going on|happening)(?:\s+in\s+the\s+news)?\b"
    r"|"
    r"\bwhat(?:'s| is)\s+(?:the\s+)?latest\s+(?:going\s+on|in\s+the\s+news)\b"
    r"|"
    r"\b(?:search|look up|find)\s+(?:the\s+)?(?:web|online|internet)\b"
    r"|"
    r"\b(?:weather|stock price|score)\s+(?:today|now|this week)\b"
    r"|"
    r"\b(?:what'?s?|what)\s+(?:going on|happening)\b"
    r"|"
    r"\b(?:stock|stocks|share price|ticker)\b.*\b(?:nvidia|nvda|nvdia)\b"
    r"|"
    r"\b(?:nvidia|nvda|nvdia)\b.*\b(?:stock|stocks|price|news)\b"
    r"|"
    r"\b(?:internet|interned|online)\b.*\b(?:news|going on|happening)\b"
    r")",
    re.IGNORECASE,
)

_CAPABILITY_ONLY_RE = re.compile(
    r"^\s*(?:can you|do you|are you able to)\b",
    re.IGNORECASE,
)


def suggest_web_search_query(user_text: str) -> str | None:
    """
    If the user message needs live web data and Main did not DELEGATE,
    return a search query (usually the user's words). Otherwise None.
    """
    text = user_text.strip()
    if len(text) < 10:
        return None
    if _CAPABILITY_ONLY_RE.match(text) and "search" not in text.lower():
        return None
    if not _WEB_INFO_RE.search(text):
        return None
    log.debug("tool_intent.auto_web_search", query=text[:120])
    return text[:200]
