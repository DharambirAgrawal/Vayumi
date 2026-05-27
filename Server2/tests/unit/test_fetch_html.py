from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from server.tools.fetch_html import fetch_html
from server.tools.page_fetch import PageFetchResult


@pytest.mark.asyncio
async def test_fetch_html_returns_raw_html() -> None:
    page = PageFetchResult(
        url="https://example.com",
        status="ok",
        html="<html><title>T</title><body>Hi</body></html>",
        fetch_mode="static",
        title="T",
        char_count=40,
    )
    with patch(
        "server.tools.fetch_html._fetch_raw_html",
        new_callable=AsyncMock,
        return_value=page,
    ):
        result = await fetch_html(user_id="u1", url="https://example.com")

    assert result.status == "ok"
    assert "<html>" in result.data["html"]
    assert result.data["fetch_mode"] == "static"
