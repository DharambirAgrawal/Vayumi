from __future__ import annotations

from server.logger import get_logger
from server.tools.page_fetch import fetch_page
from server.tools.registry import ToolResult

log = get_logger("tools.summarize_url")


async def summarize_url(
    *,
    user_id: str,
    url: str,
    dynamic: bool = False,
    allow_dynamic_fallback: bool = True,
    static_timeout_s: float = 20.0,
    dynamic_timeout_ms: int = 30_000,
    min_extract_chars: int = 400,
    max_article_chars: int = 12_000,
) -> ToolResult:
    """Fetch a URL and return normalized article text (trafilatura + fallback)."""
    del user_id

    page = await fetch_page(
        url,
        allow_dynamic=allow_dynamic_fallback,
        force_dynamic=dynamic,
        static_timeout_s=static_timeout_s,
        dynamic_timeout_ms=dynamic_timeout_ms,
        min_extract_chars=min_extract_chars,
        max_article_chars=max_article_chars,
    )
    if page.status != "ok":
        return ToolResult(
            status="error",
            summary=page.error or "could not extract article",
            data={"url": url, "fetch_mode": page.fetch_mode},
            retryable=True,
        )

    log.info(
        "tools.summarize_url.ok",
        url=url[:80],
        fetch_mode=page.fetch_mode,
        chars=page.char_count,
        extract=page.extract_method,
    )
    return ToolResult(
        status="ok",
        summary=f"Article extracted ({page.char_count} chars, {page.fetch_mode})",
        data={
            "url": url,
            "title": page.title,
            "text": page.text,
            "fetch_mode": page.fetch_mode,
            "extract_method": page.extract_method,
            "char_count": page.char_count,
        },
    )
