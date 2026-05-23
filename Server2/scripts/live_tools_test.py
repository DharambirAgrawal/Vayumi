#!/usr/bin/env python3
"""
Live integration test — real HTTP/Tavily/Scrapling, no mocks.
Run: cd Server2 && source venv/bin/activate && python scripts/live_tools_test.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.config import get_settings
from server.tools import build_tool_registry, build_tool_runner
from server.tools.fetch_url import fetch_url
from server.tools.page_fetch import fetch_page
from server.tools.web_search import web_search
from server.tools.deep_search import deep_search


def _banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def _preview(text: str, limit: int = 900) -> str:
    t = text.strip()
    if len(t) <= limit:
        return t
    return t[:limit] + "\n… [truncated for display]"


async def run_fetch_url_cases(settings) -> list[bool]:
    _banner("1) fetch_url — real URLs (static first)")
    cases = [
        ("Wikipedia (static HTML)", "https://en.wikipedia.org/wiki/Mars", False),
        ("Example.com (minimal)", "https://example.com", False),
    ]
    ok_all = True
    for label, url, dynamic in cases:
        t0 = time.perf_counter()
        result = await fetch_url(
            user_id="live_test",
            url=url,
            dynamic=dynamic,
            allow_dynamic_fallback=True,
            tavily_api_key=settings.tavily_api_key,
        )
        elapsed = time.perf_counter() - t0
        print(f"\n--- {label} ({elapsed:.1f}s) status={result.status} ---")
        print(f"summary: {result.summary}")
        if result.status == "ok":
            d = result.data
            print(f"fetch_mode={d.get('fetch_mode')} extract={d.get('extract_method')} chars={d.get('char_count')}")
            print(_preview(str(d.get("text", ""))))
        else:
            print(f"error data: {result.data}")
            ok_all = False
    return ok_all


async def run_fetch_page_ladder(settings) -> bool:
    _banner("2) fetch_page ladder — static vs forced dynamic")
    url = "https://en.wikipedia.org/wiki/Mars"
    for label, dynamic, allow_dyn in [
        ("static only", False, False),
        ("static + fallback", False, True),
    ]:
        t0 = time.perf_counter()
        page = await fetch_page(
            url,
            allow_dynamic=allow_dyn,
            force_dynamic=dynamic,
            static_timeout_s=float(settings.deep_search_static_timeout_s),
            dynamic_timeout_ms=settings.deep_search_dynamic_timeout_ms,
            min_extract_chars=settings.deep_search_min_extract_chars,
            max_article_chars=settings.deep_search_max_chars_per_article,
        )
        elapsed = time.perf_counter() - t0
        print(f"\n--- {label} ({elapsed:.1f}s) status={page.status} mode={page.fetch_mode} ---")
        if page.status == "ok":
            print(f"extract={page.extract_method} chars={page.char_count}")
            print(_preview(page.text))
        else:
            print(f"error: {page.error}")
    return True


async def run_web_search(settings) -> bool:
    _banner("3) web_search — quick snippets (Main path)")
    query = "NVIDIA stock news today"
    t0 = time.perf_counter()
    result = await web_search(
        user_id="live_test",
        query=query,
        max_results=5,
        search_depth="basic",
        tavily_api_key=settings.tavily_api_key,
    )
    elapsed = time.perf_counter() - t0
    print(f"time={elapsed:.1f}s status={result.status} summary={result.summary}")
    for idx, row in enumerate(result.data.get("results", [])[:5], 1):
        if isinstance(row, dict):
            print(f"  {idx}. {row.get('title','')[:80]}")
            print(f"     {row.get('url','')[:100]}")
            print(f"     snippet: {_preview(str(row.get('snippet','')), 200)}")
    return result.status == "ok"


async def run_deep_search(settings) -> bool:
    _banner("4) deep_search — Tavily + real article reads")
    queries = [
        "NVIDIA stock earnings news May 2026",
        "latest AI chip industry news",
    ]
    ok = True
    for query in queries:
        print(f"\n>>> query: {query}")
        t0 = time.perf_counter()
        result = await deep_search(
            user_id="live_test",
            query=query,
            max_urls=2,
            search_depth="advanced",
            dynamic=False,
            allow_dynamic_fallback=True,
            tavily_api_key=settings.tavily_api_key,
            static_timeout_s=float(settings.deep_search_static_timeout_s),
            dynamic_timeout_ms=settings.deep_search_dynamic_timeout_ms,
            min_extract_chars=settings.deep_search_min_extract_chars,
            max_article_chars=settings.deep_search_max_chars_per_article,
        )
        elapsed = time.perf_counter() - t0
        print(f"time={elapsed:.1f}s status={result.status}")
        print(f"summary: {result.summary}")
        print(f"backend: {result.data.get('discover_backend')}")
        for art in result.data.get("articles", []):
            if not isinstance(art, dict):
                continue
            print(f"\n  [{art.get('status')}] {art.get('title','')[:70]}")
            print(f"  url: {art.get('url','')[:100]}")
            print(f"  fetch: {art.get('fetch_mode')} extract: {art.get('extract_method')} chars: {art.get('char_count')}")
            if art.get("error"):
                print(f"  error: {art.get('error')}")
            print(_preview(str(art.get("text", "")), 600))
        if result.status != "ok":
            ok = False
    return ok


async def run_tool_runner_events(settings) -> bool:
    _banner("5) ToolRunner — tool_started / tool_done events (like activity feed)")
    registry = build_tool_registry(settings)
    runner = build_tool_runner(registry)
    events: list[tuple[str, str, str]] = []

    async def on_event(kind: str, task_id: str, summary: str) -> None:
        events.append((kind, task_id, summary))
        print(f"  EVENT {kind}: {summary}")

    from server.tools.registry import ToolCall

    t0 = time.perf_counter()
    result = await runner.execute(
        "live-task-1",
        ToolCall(
            name="deep_search",
            args={"query": "OpenAI latest news", "max_urls": 2},
            capability="research",
        ),
        user_id="live_test",
        on_event=on_event,
    )
    elapsed = time.perf_counter() - t0
    print(f"\nrunner time={elapsed:.1f}s status={result.status}")
    print(f"events captured: {len(events)} ({', '.join(e[0] for e in events)})")
    return result.status == "ok" and len(events) >= 2


async def main() -> int:
    settings = get_settings()
    print("Live tools test (real network)")
    print(f"tavily={'yes' if settings.tavily_api_key else 'no (DDG only)'}")
    print("dynamic_fallback=True (static first, headless browser if thin)")

    results: list[tuple[str, bool]] = []
    results.append(("fetch_url", await run_fetch_url_cases(settings)))
    results.append(("fetch_page", await run_fetch_page_ladder(settings)))
    results.append(("web_search", await run_web_search(settings)))
    results.append(("deep_search", await run_deep_search(settings)))
    results.append(("tool_events", await run_tool_runner_events(settings)))

    _banner("SUMMARY")
    code = 0
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {name}: {status}")
        if not ok:
            code = 1
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
