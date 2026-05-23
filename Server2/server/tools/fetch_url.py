from __future__ import annotations

from server.logger import get_logger
from server.tools.page_fetch import fetch_page
from server.tools.registry import ToolResult

log = get_logger("tools.fetch_url")


async def fetch_url(
    *,
    user_id: str,
    url: str,
    dynamic: bool = False,
    allow_dynamic_fallback: bool = True,
    tavily_api_key: str | None = None,  # unused; kept for registry partial symmetry
) -> ToolResult:
    del user_id, tavily_api_key
    page = await fetch_page(
        url,
        allow_dynamic=allow_dynamic_fallback,
        force_dynamic=dynamic,
    )
    if page.status != "ok":
        return ToolResult(
            status="error",
            summary=page.error or "fetch failed",
            data={"url": url, "fetch_mode": page.fetch_mode},
            retryable=True,
        )

    log.info(
        "tools.fetch_url.ok",
        url=url[:80],
        fetch_mode=page.fetch_mode,
        chars=page.char_count,
        extract=page.extract_method,
    )
    return ToolResult(
        status="ok",
        summary=f"Fetched article ({page.char_count} chars, {page.fetch_mode})",
        data={
            "url": url,
            "title": page.title,
            "text": page.text,
            "fetch_mode": page.fetch_mode,
            "extract_method": page.extract_method,
            "char_count": page.char_count,
        },
    )
