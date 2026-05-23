from __future__ import annotations

import re
from html import unescape

from server.logger import get_logger

log = get_logger("tools.page_extract")

_TAG_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_BLOCK_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\n{3,}")


def extract_article_text(
    html: str,
    url: str,
    *,
    min_useful_chars: int = 200,
) -> tuple[str, str]:
    """
    Return (text, method) where method is trafilatura | fallback | empty.
    """
    if not html or not html.strip():
        return "", "empty"

    text = _extract_trafilatura(html, url)
    if len(text) >= min_useful_chars:
        return _truncate(text), "trafilatura"

    text = _extract_fallback(html)
    if len(text) >= min_useful_chars:
        log.debug("page_extract.fallback_used", url=url[:80], chars=len(text))
        return _truncate(text), "fallback"

    if text.strip():
        return _truncate(text), "fallback_short"
    return "", "empty"


def _extract_trafilatura(html: str, url: str) -> str:
    try:
        import trafilatura
    except ImportError:
        log.warning("page_extract.trafilatura_missing")
        return ""

    try:
        downloaded = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
    except Exception as exc:
        log.debug("page_extract.trafilatura_failed", url=url[:80], error=str(exc))
        return ""
    if not downloaded:
        return ""
    return downloaded.strip()


def _extract_fallback(html: str) -> str:
    cleaned = _TAG_RE.sub(" ", html)
    cleaned = _BLOCK_RE.sub("\n", cleaned)
    cleaned = unescape(cleaned)
    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    # Drop very short nav/footer noise when possible
    kept = [ln for ln in lines if len(ln) > 24 or len(lines) < 8]
    if not kept:
        kept = lines
    text = "\n".join(kept)
    return _WS_RE.sub("\n\n", text).strip()


def _truncate(text: str, max_chars: int = 12_000) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + "\n… [truncated]"
