from __future__ import annotations

import asyncio

from server.logger import get_logger
from server.tools.page_fetch import (
    PageFetchResult,
    fetch_dynamic_async,
    fetch_static_sync,
    validate_http_url,
)
from server.tools.registry import ToolResult

log = get_logger("tools.fetch_html")

_MAX_HTML_CHARS = 200_000


async def fetch_html(
    *,
    user_id: str,
    url: str,
    dynamic: bool = False,
    allow_dynamic_fallback: bool = True,
    static_timeout_s: float = 20.0,
    dynamic_timeout_ms: int = 30_000,
) -> ToolResult:
    """Return raw HTML for a URL (no article extraction)."""
    del user_id

    err = validate_http_url(url)
    if err:
        return ToolResult(status="error", summary=err, data={"url": url}, retryable=False)

    page = await _fetch_raw_html(
        url,
        dynamic=dynamic,
        allow_dynamic_fallback=allow_dynamic_fallback,
        static_timeout_s=static_timeout_s,
        dynamic_timeout_ms=dynamic_timeout_ms,
    )
    if page.status != "ok" or not page.html.strip():
        return ToolResult(
            status="error",
            summary=page.error or "fetch failed",
            data={"url": url, "fetch_mode": page.fetch_mode},
            retryable=True,
        )

    html = page.html
    truncated = False
    if len(html) > _MAX_HTML_CHARS:
        html = html[: _MAX_HTML_CHARS - 40] + "\n<!-- truncated by server -->"
        truncated = True

    log.info(
        "tools.fetch_html.ok",
        url=url[:80],
        fetch_mode=page.fetch_mode,
        chars=len(html),
        truncated=truncated,
    )
    return ToolResult(
        status="ok",
        summary=f"Fetched HTML ({len(html)} chars, {page.fetch_mode})",
        data={
            "url": url,
            "html": html,
            "title": page.title,
            "fetch_mode": page.fetch_mode,
            "char_count": len(html),
            "truncated": truncated,
        },
    )


async def _fetch_raw_html(
    url: str,
    *,
    dynamic: bool,
    allow_dynamic_fallback: bool,
    static_timeout_s: float,
    dynamic_timeout_ms: int,
) -> PageFetchResult:
    html = ""
    mode = "none"
    last_error: str | None = None

    if not dynamic:
        try:
            html = await asyncio.to_thread(
                fetch_static_sync, url, timeout_s=static_timeout_s
            )
            mode = "static"
        except Exception as exc:
            last_error = str(exc)

    need_dynamic = dynamic or (allow_dynamic_fallback and not html.strip())
    if need_dynamic:
        try:
            html = await fetch_dynamic_async(url, timeout_ms=dynamic_timeout_ms)
            mode = "dynamic"
            last_error = None
        except ImportError:
            last_error = "dynamic fetch unavailable (install scrapling fetchers)"
        except Exception as exc:
            last_error = str(exc)

    if not html.strip():
        return PageFetchResult(
            url=url,
            status="error",
            error=last_error or "empty response",
            fetch_mode=mode,
        )

    from server.tools.page_fetch import _guess_title

    return PageFetchResult(
        url=url,
        status="ok",
        html=html,
        fetch_mode=mode,  # type: ignore[arg-type]
        title=_guess_title(html),
        char_count=len(html),
    )
