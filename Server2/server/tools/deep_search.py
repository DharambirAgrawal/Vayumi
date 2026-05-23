from __future__ import annotations

import asyncio

from server.logger import get_logger
from server.tools.groq_compress import groq_compress_article
from server.tools.page_fetch import PageFetchResult, fetch_page, validate_http_url
from server.tools.registry import ToolResult
from server.tools.web_search import SearchDepth, _search_ddg, _search_tavily

log = get_logger("tools.deep_search")


async def _discover_urls(
    query: str,
    *,
    max_urls: int,
    search_depth: SearchDepth,
    tavily_api_key: str | None,
) -> tuple[list[dict[str, str]], str]:
    rows: list[dict[str, str]] = []
    backend = "none"

    if tavily_api_key:
        try:
            rows = await _search_tavily(
                tavily_api_key, query, max_urls, search_depth
            )
            backend = "tavily"
        except Exception as exc:
            log.warning("deep_search.tavily_failed", error=str(exc))

    if not rows:
        try:
            rows = await _search_ddg(query, max_urls)
            backend = "duckduckgo"
        except Exception as exc:
            log.warning("deep_search.ddg_failed", error=str(exc))
            return [], backend

    return rows, backend


async def _read_one_url(
    row: dict[str, str],
    *,
    allow_dynamic: bool,
    force_dynamic: bool,
    static_timeout_s: float,
    dynamic_timeout_ms: int,
    min_extract_chars: int,
    max_article_chars: int,
) -> dict[str, object]:
    url = row.get("url", "")
    err = validate_http_url(url)
    if err:
        return {
            "url": url,
            "title": row.get("title", ""),
            "snippet": row.get("snippet", ""),
            "status": "skipped",
            "error": err,
            "text": "",
            "fetch_mode": "none",
        }

    page: PageFetchResult = await fetch_page(
        url,
        allow_dynamic=allow_dynamic,
        force_dynamic=force_dynamic,
        static_timeout_s=static_timeout_s,
        dynamic_timeout_ms=dynamic_timeout_ms,
        min_extract_chars=min_extract_chars,
        max_article_chars=max_article_chars,
    )
    if page.status == "ok":
        return {
            "url": url,
            "title": page.title or row.get("title", ""),
            "snippet": row.get("snippet", ""),
            "status": "ok",
            "text": page.text,
            "fetch_mode": page.fetch_mode,
            "extract_method": page.extract_method,
            "char_count": page.char_count,
        }

    # Keep Tavily snippet when full read fails (paywall, bot block, etc.)
    fallback_text = row.get("snippet", "")
    return {
        "url": url,
        "title": row.get("title", ""),
        "snippet": fallback_text,
        "status": "partial",
        "error": page.error,
        "text": fallback_text,
        "fetch_mode": page.fetch_mode,
        "extract_method": "search_snippet_fallback",
        "char_count": len(fallback_text),
    }


async def deep_search(
    *,
    user_id: str,
    query: str,
    max_urls: int = 3,
    search_depth: SearchDepth = "advanced",
    dynamic: bool = False,
    allow_dynamic_fallback: bool = True,
    tavily_api_key: str | None = None,
    groq_api_key: str | None = None,
    static_timeout_s: float = 20.0,
    dynamic_timeout_ms: int = 30_000,
    min_extract_chars: int = 400,
    max_article_chars: int = 6000,
) -> ToolResult:
    del user_id
    query = query.strip()
    if not query:
        return ToolResult(status="error", summary="query is required", retryable=False)

    max_urls = max(1, min(max_urls, 5))
    if search_depth not in ("basic", "advanced"):
        search_depth = "advanced"

    rows, discover_backend = await _discover_urls(
        query,
        max_urls=max_urls,
        search_depth=search_depth,
        tavily_api_key=tavily_api_key,
    )
    if not rows:
        return ToolResult(
            status="ok",
            summary=f"No URLs found for {query!r}",
            data={
                "query": query,
                "discover_backend": discover_backend,
                "articles": [],
            },
        )

    allow_dynamic = allow_dynamic_fallback or dynamic
    tasks = [
        _read_one_url(
            row,
            allow_dynamic=allow_dynamic,
            force_dynamic=dynamic,
            static_timeout_s=static_timeout_s,
            dynamic_timeout_ms=dynamic_timeout_ms,
            min_extract_chars=min_extract_chars,
            max_article_chars=max_article_chars,
        )
        for row in rows[:max_urls]
    ]
    articles = list(await asyncio.gather(*tasks))

    if groq_api_key:
        compressed: list[dict[str, object]] = []
        for article in articles:
            text = str(article.get("text", ""))
            if article.get("status") == "ok" and len(text) >= 2500:
                text = await groq_compress_article(
                    api_key=groq_api_key,
                    query=query,
                    title=str(article.get("title", "")),
                    url=str(article.get("url", "")),
                    text=text,
                )
                article = {**article, "text": text, "compressed_via": "groq"}
            compressed.append(article)
        articles = compressed

    ok_count = sum(1 for a in articles if a.get("status") == "ok")
    partial_count = sum(1 for a in articles if a.get("status") == "partial")
    summary = (
        f"Deep search: {ok_count} full read(s), {partial_count} partial/snippet"
        f" from {discover_backend}"
    )

    log.info(
        "tools.deep_search.complete",
        query=query[:80],
        urls=len(articles),
        ok=ok_count,
        partial=partial_count,
        discover=discover_backend,
    )

    return ToolResult(
        status="ok",
        summary=summary,
        data={
            "query": query,
            "discover_backend": discover_backend,
            "articles": articles,
            "max_urls": max_urls,
            "search_depth": search_depth,
        },
    )
