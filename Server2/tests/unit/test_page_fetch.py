from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from server.tools.page_fetch import (
    fetch_page,
    fetch_static_sync,
    validate_http_url,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "html"


def test_validate_http_url_rejects_bad_schemes() -> None:
    assert validate_http_url("ftp://example.com") is not None
    assert validate_http_url("javascript:alert(1)") is not None
    assert validate_http_url("https://example.com/article") is None


def test_validate_rejects_localhost() -> None:
    assert validate_http_url("http://127.0.0.1/test") is not None


def test_fetch_static_sync_from_fixture() -> None:
    html = (FIXTURES / "news_article.html").read_text(encoding="utf-8")

    class _FakePage:
        html_content = html

    with patch("scrapling.fetchers.Fetcher.get", return_value=_FakePage()):
        out = fetch_static_sync("https://news.example/story")
    assert "NVIDIA" in out


@pytest.mark.asyncio
async def test_fetch_page_static_ok() -> None:
    html = (FIXTURES / "news_article.html").read_text(encoding="utf-8")

    def _fake_static(url: str, *, timeout_s: float = 20.0) -> str:
        del url, timeout_s
        return html

    with patch("server.tools.page_fetch.fetch_static_sync", side_effect=_fake_static):
        with patch("server.tools.page_fetch.fetch_dynamic_async") as dyn:
            result = await fetch_page(
                "https://news.example/story",
                allow_dynamic=False,
                min_extract_chars=100,
            )
    dyn.assert_not_called()
    assert result.status == "ok"
    assert result.fetch_mode == "static"
    assert result.char_count > 100


@pytest.mark.asyncio
async def test_fetch_page_thin_static_triggers_dynamic() -> None:
    thin = (FIXTURES / "thin_shell.html").read_text(encoding="utf-8")
    rich = (FIXTURES / "news_article.html").read_text(encoding="utf-8")

    def _fake_static(url: str, *, timeout_s: float = 20.0) -> str:
        del url, timeout_s
        return thin

    async def _fake_dynamic(url: str, *, timeout_ms: int = 30_000) -> str:
        del url, timeout_ms
        return rich

    with patch("server.tools.page_fetch.fetch_static_sync", side_effect=_fake_static):
        with patch("server.tools.page_fetch.fetch_dynamic_async", side_effect=_fake_dynamic):
            result = await fetch_page(
                "https://spa.example/app",
                allow_dynamic=True,
                min_extract_chars=200,
            )
    assert result.status == "ok"
    assert result.fetch_mode == "dynamic"
    assert "NVIDIA" in result.text


@pytest.mark.asyncio
async def test_fetch_page_dynamic_import_error_keeps_partial() -> None:
    thin = (FIXTURES / "thin_shell.html").read_text(encoding="utf-8")

    def _fake_static(url: str, *, timeout_s: float = 20.0) -> str:
        del url, timeout_s
        return thin

    async def _fail_dynamic(url: str, *, timeout_ms: int = 30_000) -> str:
        del url, timeout_ms
        raise ImportError("no playwright")

    with patch("server.tools.page_fetch.fetch_static_sync", side_effect=_fake_static):
        with patch("server.tools.page_fetch.fetch_dynamic_async", side_effect=_fail_dynamic):
            result = await fetch_page(
                "https://spa.example/app",
                allow_dynamic=True,
                min_extract_chars=400,
            )
    # Dynamic unavailable; may still return thin static extract or error
    assert result.status in ("error", "ok")
    if result.status == "ok":
        assert result.char_count < 400


@pytest.mark.asyncio
async def test_fetch_page_static_failure_returns_error() -> None:
    def _boom(url: str, *, timeout_s: float = 20.0) -> str:
        del url, timeout_s
        raise ConnectionError("timeout")

    with patch("server.tools.page_fetch.fetch_static_sync", side_effect=_boom):
        result = await fetch_page("https://news.example/x", allow_dynamic=False)
    assert result.status == "error"
    assert result.error
