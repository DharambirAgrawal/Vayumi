from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from server.orchestrator.directives import plan_acknowledgment

_TRIVIAL_CHAT = frozenset({"?", "!", "??", "???", "...", "..", "…"})

_TOOL_PROMISE_ACK = (
    "let me check",
    "give me a moment",
    "just a moment",
    "gather that information",
    "fetch that",
    "look that up",
    "one sec",
    "let me fetch",
    "let me look",
    "pull that up",
    "checking that",
)

_PRICE_IN_PROSE = re.compile(r"(?:\$|€|£)\s*[\d,]+(?:\.\d+)?", re.IGNORECASE)
_STALE_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_INLINE_WEB_SEARCH_RE = re.compile(
    r"\[web_search[^\]]*\]",
    re.IGNORECASE,
)
_INLINE_WEB_SEARCH_QUERY_RE = re.compile(
    r'\[web_search\s+query=["\']([^"\']+)["\']\s*\]',
    re.IGNORECASE,
)


def is_trivial_chat_followup(text: str) -> bool:
    """True for '?', '!' etc. that should not replace a queued chat message."""
    stripped = text.strip()
    if not stripped:
        return True
    if stripped in _TRIVIAL_CHAT:
        return True
    return len(stripped) <= 2


def parse_inline_web_search_query(model_content: str | None) -> str | None:
    if not model_content:
        return None
    match = _INLINE_WEB_SEARCH_QUERY_RE.search(model_content)
    if match:
        return match.group(1).strip()
    return None


def has_inline_web_search_leak(text: str | None) -> bool:
    if not text:
        return False
    return bool(_INLINE_WEB_SEARCH_RE.search(text))


def _web_search_blob(runs: list[Any]) -> str:
    parts: list[str] = []
    for run in runs:
        tool_name = getattr(run, "tool_name", None)
        result = getattr(run, "result", None)
        if tool_name != "web_search" or result is None:
            continue
        status = getattr(result, "status", None)
        if status != "ok":
            continue
        summary = getattr(result, "summary", "") or ""
        data = getattr(result, "data", {}) or {}
        parts.append(summary)
        parts.append(json.dumps(data, ensure_ascii=False))
    return " ".join(parts)


def _normalize_price_digits(price: str) -> str:
    return re.sub(r"[^\d.]", "", price)


def answer_grounded_in_web_search(visible: str, runs: list[Any]) -> bool:
    """True when a reply is backed by real web_search data (not a guess)."""
    stripped = (visible or "").strip()
    if not stripped:
        return False
    if has_inline_web_search_leak(stripped):
        return False
    if is_tool_promise_without_data(stripped):
        return False

    ok_runs = [
        run
        for run in runs
        if getattr(run, "tool_name", None) == "web_search"
        and getattr(getattr(run, "result", None), "status", None) == "ok"
    ]
    if not ok_runs:
        return False

    blob = _web_search_blob(runs)
    if not blob.strip():
        return False

    prices = _PRICE_IN_PROSE.findall(stripped)
    if not prices:
        return True

    blob_digits = _normalize_price_digits(blob.replace(",", ""))
    for quoted in prices:
        digits = _normalize_price_digits(quoted)
        if digits and digits not in blob_digits:
            return False
    return True


def is_tool_promise_without_data(model_content: str | None) -> bool:
    if not model_content or not model_content.strip():
        return False
    lower = model_content.lower()
    if _PRICE_IN_PROSE.search(model_content):
        return False
    return any(marker in lower for marker in _TOOL_PROMISE_ACK)


def should_fallback_web_search(*, model_content: str | None) -> bool:
    """Safety net when the model skips native tool_calls (model output only)."""
    if not model_content or not model_content.strip():
        return False
    if has_inline_web_search_leak(model_content):
        return True
    if is_tool_promise_without_data(model_content):
        return True
    if answer_looks_stale(model_content):
        return True
    if _PRICE_IN_PROSE.search(model_content):
        return not answer_grounded_in_web_search(model_content, [])
    return False


def fallback_web_search_query(*, user_text: str, model_content: str | None) -> str:
    inline = parse_inline_web_search_query(model_content)
    if inline:
        return inline
    return user_text.strip()


def is_insufficient_tool_answer(text: str | None) -> bool:
    """True when tool results exist but the spoken reply has no real facts yet."""
    stripped = (text or "").strip()
    if not stripped:
        return True
    if is_tool_promise_without_data(stripped):
        return True
    if has_inline_web_search_leak(stripped):
        return True
    return False


def answer_looks_stale(visible: str, *, today_year: int | None = None) -> bool:
    """True when prose cites a calendar year before the current year."""
    year = today_year if today_year is not None else date.today().year
    for match in _STALE_YEAR_RE.finditer(visible or ""):
        cited = int(match.group(1))
        if cited < year:
            return True
    return False


def tool_status_while_searching(model_content: str | None) -> str:
    """Short safe line to show/speak while web_search runs — never stale facts."""
    if not model_content or not model_content.strip():
        return "Looking that up now."
    if should_fallback_web_search(model_content=model_content):
        ack = plan_acknowledgment(model_content)
        if (
            ack
            and is_tool_promise_without_data(ack)
            and not answer_looks_stale(ack)
        ):
            return ack
        return "Looking that up now."
    ack = plan_acknowledgment(model_content)
    return ack or "Looking that up now."


def is_web_search_only_runs(runs: list[Any]) -> bool:
    return bool(runs) and all(
        getattr(run, "tool_name", None) == "web_search" for run in runs
    )


def needs_web_search_synthesis(visible: str, runs: list[Any]) -> bool:
    """True when the visible reply should be replaced with search snippets."""
    if is_insufficient_tool_answer(visible):
        return True
    if answer_looks_stale(visible):
        return True
    if _PRICE_IN_PROSE.search(visible) and not answer_grounded_in_web_search(
        visible, runs
    ):
        return True
    return False
