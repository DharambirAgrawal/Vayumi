from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from server.tools.deep_search import deep_search
from server.tools.page_fetch import PageFetchResult
from server.tools.registry import ToolResult

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "html"

SAMPLE_ROWS = [
    {
        "title": "Story A",
        "url": "https://news.example/a",
        "snippet": "Snippet A",
        "source": "tavily",
    },
    {
        "title": "Story B",
        "url": "https://news.example/b",
        "snippet": "Snippet B",
        "source": "tavily",
    },
]


@pytest.mark.asyncio
async def test_deep_search_reads_multiple_articles() -> None:
    async def _fake_page(url: str, **kwargs: object) -> PageFetchResult:
        del kwargs
        return PageFetchResult(
            url=url,
            status="ok",
            fetch_mode="static",
            title="Title",
            text="NVIDIA GPUs " * 40,
            extract_method="trafilatura",
            char_count=400,
        )

    with patch("server.tools.deep_search._search_tavily", return_value=SAMPLE_ROWS):
        with patch("server.tools.deep_search.fetch_page", side_effect=_fake_page):
            result = await deep_search(
                user_id="u1",
                query="NVIDIA stock news",
                max_urls=2,
                tavily_api_key="key",
                allow_dynamic_fallback=False,
            )

    assert result.status == "ok"
    articles = result.data["articles"]
    assert len(articles) == 2
    assert all(a["status"] == "ok" for a in articles)
    assert "NVIDIA" in articles[0]["text"]


@pytest.mark.asyncio
async def test_deep_search_partial_uses_snippet_on_fetch_fail() -> None:
    async def _fail_page(url: str, **kwargs: object) -> PageFetchResult:
        del kwargs
        return PageFetchResult(
            url=url,
            status="error",
            error="403 forbidden",
            fetch_mode="static",
        )

    with patch("server.tools.deep_search._search_tavily", return_value=SAMPLE_ROWS[:1]):
        with patch("server.tools.deep_search.fetch_page", side_effect=_fail_page):
            result = await deep_search(
                user_id="u1",
                query="blocked site",
                max_urls=1,
                tavily_api_key="key",
            )

    assert result.status == "ok"
    article = result.data["articles"][0]
    assert article["status"] == "partial"
    assert article["text"] == "Snippet A"


@pytest.mark.asyncio
async def test_deep_search_no_urls() -> None:
    with patch("server.tools.deep_search._search_tavily", return_value=[]):
        with patch("server.tools.deep_search._search_ddg", return_value=[]):
            result = await deep_search(
                user_id="u1",
                query="obscure xyzzy",
                tavily_api_key="key",
            )
    assert result.status == "ok"
    assert result.data["articles"] == []


@pytest.mark.asyncio
async def test_deep_search_requires_query() -> None:
    result = await deep_search(user_id="u1", query="  ")
    assert result.status == "error"


def test_render_deep_search_prompt() -> None:
    from server.tools.registry import render_tool_result_for_prompt

    result = ToolResult(
        status="ok",
        summary="2 articles",
        data={
            "articles": [
                {
                    "url": "https://a",
                    "title": "A",
                    "status": "ok",
                    "text": "Body " * 50,
                }
            ]
        },
    )
    block = render_tool_result_for_prompt("deep_search", result)
    assert "Article 1" in block
    assert "Body" in block
