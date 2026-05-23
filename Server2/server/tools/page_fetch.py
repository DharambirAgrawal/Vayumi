from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import httpx

from server.logger import get_logger
from server.tools.page_extract import extract_article_text

log = get_logger("tools.page_fetch")

FetchMode = Literal["static", "dynamic", "none"]
FetchStatus = Literal["ok", "error", "skipped"]


@dataclass(frozen=True)
class PageFetchResult:
    url: str
    status: FetchStatus
    html: str = ""
    fetch_mode: FetchMode = "none"
    error: str | None = None
    title: str = ""
    text: str = ""
    extract_method: str = ""
    char_count: int = 0


def validate_http_url(url: str) -> str | None:
    """Return error message if URL is not fetchable, else None."""
    raw = url.strip()
    if not raw:
        return "url is required"
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return "url must use http or https"
    if not parsed.netloc:
        return "url must include a host"
    lowered = parsed.netloc.lower()
    if lowered in ("localhost", "127.0.0.1", "0.0.0.0"):
        return "localhost URLs are not allowed"
    path = (parsed.path or "").lower()
    if path.endswith(".pdf") or path.endswith(".zip"):
        return "binary document URLs are not supported"
    return None


def page_html_from_scrapling(page: object) -> str:
    """Normalize Scrapling (or test double) page objects to HTML string."""
    for attr in ("html_content", "html", "content", "body", "text"):
        value = getattr(page, attr, None)
        if isinstance(value, str) and value.strip():
            if attr == "text" and "<" not in value[:200]:
                continue
            return value
    if hasattr(page, "css"):
        try:
            # Last resort: not ideal for articles but better than nothing
            chunks = page.css("body ::text").getall()  # type: ignore[union-attr]
            if chunks:
                return "<body>" + "".join(f"<p>{c}</p>" for c in chunks if c.strip()) + "</body>"
        except Exception:
            pass
    return ""


def fetch_static_sync(url: str, *, timeout_s: float = 20.0) -> str:
    """Fast/light fetch — Scrapling Fetcher, httpx fallback if Scrapling missing."""
    try:
        from scrapling.fetchers import Fetcher

        page = Fetcher.get(url, timeout=int(timeout_s))
        html = page_html_from_scrapling(page)
        if html:
            return html
    except ImportError:
        log.debug("page_fetch.scrapling_missing_static", url=url[:80])
    except Exception as exc:
        log.debug("page_fetch.static_failed", url=url[:80], error=str(exc))
        raise

    return _fetch_static_httpx_sync(url, timeout_s=timeout_s)


def _fetch_static_httpx_sync(url: str, *, timeout_s: float) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; VayumiServer2/0.1; +https://vayumi.local)",
    }
    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower() and "text" not in content_type.lower():
            raise ValueError(f"unsupported content-type: {content_type}")
        return response.text


async def fetch_dynamic_async(url: str, *, timeout_ms: int = 30_000) -> str:
    """Heavy fetch — Playwright via Scrapling AsyncDynamicSession."""

    async def _run() -> str:
        from scrapling.fetchers import AsyncDynamicSession

        async with AsyncDynamicSession(
            headless=True,
            disable_resources=True,
            network_idle=True,
        ) as session:
            page = await session.fetch(url, timeout=timeout_ms)
            return page_html_from_scrapling(page)

    return await asyncio.wait_for(_run(), timeout=timeout_ms / 1000 + 15)


async def fetch_page(
    url: str,
    *,
    allow_dynamic: bool = False,
    static_timeout_s: float = 20.0,
    dynamic_timeout_ms: int = 30_000,
    min_extract_chars: int = 400,
    max_article_chars: int = 12_000,
    force_dynamic: bool = False,
) -> PageFetchResult:
    """
    Fetch and extract article text. Static first; dynamic only when needed or forced.
    """
    err = validate_http_url(url)
    if err:
        return PageFetchResult(url=url, status="error", error=err)

    html = ""
    mode: FetchMode = "none"
    last_error: str | None = None

    if not force_dynamic:
        try:
            html = await asyncio.to_thread(
                fetch_static_sync, url, timeout_s=static_timeout_s
            )
            mode = "static"
        except Exception as exc:
            last_error = str(exc)
            log.info("page_fetch.static_error", url=url[:80], error=last_error)

    text = ""
    method = ""
    if html:
        text, method = extract_article_text(
            html, url, min_useful_chars=min_extract_chars // 2
        )

    need_dynamic = force_dynamic or (
        allow_dynamic and len(text) < min_extract_chars
    )
    if need_dynamic:
        try:
            html = await fetch_dynamic_async(url, timeout_ms=dynamic_timeout_ms)
            mode = "dynamic"
            text, method = extract_article_text(
                html, url, min_useful_chars=min_extract_chars // 2
            )
            last_error = None
        except ImportError:
            last_error = "dynamic fetch unavailable (run scrapling install)"
        except Exception as exc:
            last_error = str(exc)
            log.info("page_fetch.dynamic_error", url=url[:80], error=last_error)

    if not html and last_error:
        return PageFetchResult(
            url=url,
            status="error",
            error=last_error,
            fetch_mode=mode,
        )

    if not text.strip():
        return PageFetchResult(
            url=url,
            status="error",
            html=html,
            fetch_mode=mode,
            error=last_error or "no extractable article text",
            extract_method=method or "empty",
        )

    if len(text) > max_article_chars:
        text = text[: max_article_chars - 20].rstrip() + "\n… [truncated]"

    title = _guess_title(html)
    return PageFetchResult(
        url=url,
        status="ok",
        html=html,
        fetch_mode=mode,
        title=title,
        text=text,
        extract_method=method,
        char_count=len(text),
    )


def _guess_title(html: str) -> str:
    match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    if match:
        from html import unescape as _ue

        return _ue(match.group(1)).strip()[:300]
    return ""
