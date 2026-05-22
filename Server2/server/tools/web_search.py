from __future__ import annotations

import asyncio
import re
from html import unescape
from typing import Literal
from urllib.parse import quote_plus

import httpx

from server.logger import get_logger
from server.tools.registry import ToolResult

SearchDepth = Literal["basic", "advanced"]

log = get_logger("tools.web_search")

_SEARCH_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'.*?<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return unescape(_TAG_RE.sub("", text)).strip()


def _normalize_row(
    *,
    title: str,
    url: str,
    snippet: str,
    source: str,
) -> dict[str, str]:
    return {
        "title": title.strip()[:300],
        "url": url.strip(),
        "snippet": snippet.strip()[:500],
        "source": source,
    }


def _tavily_search_sync(
    api_key: str,
    query: str,
    max_results: int,
    search_depth: SearchDepth,
) -> dict[str, object]:
    from tavily import TavilyClient

    client = TavilyClient(api_key=api_key)
    return client.search(
        query=query,
        max_results=max_results,
        search_depth=search_depth,
    )


async def _search_tavily(
    api_key: str,
    query: str,
    max_results: int,
    search_depth: SearchDepth,
) -> list[dict[str, str]]:
    response = await asyncio.to_thread(
        _tavily_search_sync, api_key, query, max_results, search_depth
    )
    rows: list[dict[str, str]] = []
    for item in response.get("results", []):
        if not isinstance(item, dict):
            continue
        rows.append(
            _normalize_row(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                snippet=str(item.get("content", item.get("snippet", ""))),
                source="tavily",
            )
        )
    return rows


async def _search_ddg(query: str, max_results: int) -> list[dict[str, str]]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; VayumiServer2/0.1; +https://vayumi.local)"
        ),
    }
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        html = response.text

    rows: list[dict[str, str]] = []
    for match in _SEARCH_RESULT.finditer(html):
        rows.append(
            _normalize_row(
                title=_strip_html(match.group("title")),
                url=match.group("url"),
                snippet=_strip_html(match.group("snippet")),
                source="duckduckgo",
            )
        )
        if len(rows) >= max_results:
            break
    return rows


async def web_search(
    *,
    user_id: str,
    query: str,
    max_results: int = 5,
    search_depth: SearchDepth = "basic",
    tavily_api_key: str | None = None,
) -> ToolResult:
    del user_id
    query = query.strip()
    if not query:
        return ToolResult(status="error", summary="query is required", retryable=False)

    max_results = max(1, min(max_results, 10))
    if search_depth not in ("basic", "advanced"):
        search_depth = "basic"
    rows: list[dict[str, str]] = []
    backend = "none"

    if tavily_api_key:
        try:
            rows = await _search_tavily(
                tavily_api_key, query, max_results, search_depth
            )
            backend = "tavily"
        except Exception as exc:
            log.warning("tools.web_search.tavily_failed", error=str(exc))

    if not rows:
        try:
            rows = await _search_ddg(query, max_results)
            backend = "duckduckgo"
        except Exception as exc:
            log.warning("tools.web_search.ddg_failed", error=str(exc))
            return ToolResult(
                status="error",
                summary=f"Web search failed: {exc}",
                retryable=True,
            )

    if not rows:
        return ToolResult(
            status="ok",
            summary=f"No results for {query!r}",
            data={"results": [], "backend": backend},
        )

    return ToolResult(
        status="ok",
        summary=f"{len(rows)} result(s) from {backend}",
        data={
            "results": rows,
            "backend": backend,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
        },
    )
