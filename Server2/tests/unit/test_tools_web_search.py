from __future__ import annotations

import pytest

import server.tools.web_search as web_search_module
from server.tools.web_search import _normalize_row


def test_normalize_row_shape() -> None:
    row = _normalize_row(
        title="Title",
        url="https://example.com",
        snippet="Snippet text",
        source="tavily",
    )
    assert row == {
        "title": "Title",
        "url": "https://example.com",
        "snippet": "Snippet text",
        "source": "tavily",
    }


@pytest.mark.asyncio
async def test_web_search_tavily_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_tavily(
        api_key: str,
        query: str,
        max_results: int,
        search_depth: str = "basic",
    ) -> list[dict[str, str]]:
        del api_key, max_results, search_depth
        return [
            _normalize_row(
                title="AI News",
                url="https://news.example/1",
                snippet="Breaking",
                source="tavily",
            )
        ]

    monkeypatch.setattr(web_search_module, "_search_tavily", fake_tavily)

    result = await web_search_module.web_search(
        user_id="u1",
        query="latest AI news",
        max_results=3,
        tavily_api_key="tvly-test",
    )
    assert result.status == "ok"
    assert result.data["backend"] == "tavily"
    assert len(result.data["results"]) == 1
    assert result.data["results"][0]["source"] == "tavily"


@pytest.mark.asyncio
async def test_web_search_ddg_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_tavily(
        api_key: str,
        query: str,
        max_results: int,
        search_depth: str = "basic",
    ) -> list[dict[str, str]]:
        del api_key, query, max_results, search_depth
        raise RuntimeError("tavily down")

    async def fake_ddg(query: str, max_results: int) -> list[dict[str, str]]:
        del query, max_results
        return [
            _normalize_row(
                title="DDG Hit",
                url="https://ddg.example",
                snippet="from ddg",
                source="duckduckgo",
            )
        ]

    monkeypatch.setattr(web_search_module, "_search_tavily", fail_tavily)
    monkeypatch.setattr(web_search_module, "_search_ddg", fake_ddg)

    result = await web_search_module.web_search(
        user_id="u1",
        query="weather",
        tavily_api_key="tvly-test",
    )
    assert result.status == "ok"
    assert result.data["backend"] == "duckduckgo"
    assert result.data["results"][0]["title"] == "DDG Hit"


@pytest.mark.asyncio
async def test_web_search_no_key_uses_ddg(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ddg(query: str, max_results: int) -> list[dict[str, str]]:
        del query, max_results
        return [
            _normalize_row(
                title="Only DDG",
                url="https://x",
                snippet="s",
                source="duckduckgo",
            )
        ]

    monkeypatch.setattr(web_search_module, "_search_ddg", fake_ddg)

    result = await web_search_module.web_search(
        user_id="u1", query="test", tavily_api_key=None
    )
    assert result.status == "ok"
    assert result.data["backend"] == "duckduckgo"
