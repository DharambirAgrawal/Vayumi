from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from server.tools.page_fetch import PageFetchResult
from server.tools.summarize_url import summarize_url


@pytest.mark.asyncio
async def test_summarize_url_returns_normalized_article() -> None:
    page = PageFetchResult(
        url="https://example.com/article",
        status="ok",
        title="Example Article",
        text="This is the extracted article body with enough content.",
        fetch_mode="static",
        extract_method="trafilatura",
        char_count=52,
    )
    with patch(
        "server.tools.summarize_url.fetch_page",
        new_callable=AsyncMock,
        return_value=page,
    ):
        result = await summarize_url(
            user_id="u1",
            url="https://example.com/article",
        )

    assert result.status == "ok"
    assert "extracted" in result.summary.lower()
    assert result.data["title"] == "Example Article"
    assert "extracted article body" in result.data["text"]
    assert result.data["extract_method"] == "trafilatura"


@pytest.mark.asyncio
async def test_summarize_url_error_on_fetch_fail() -> None:
    page = PageFetchResult(
        url="https://example.com/bad",
        status="error",
        error="blocked",
        fetch_mode="static",
    )
    with patch(
        "server.tools.summarize_url.fetch_page",
        new_callable=AsyncMock,
        return_value=page,
    ):
        result = await summarize_url(user_id="u1", url="https://example.com/bad")

    assert result.status == "error"
    assert result.retryable is True
