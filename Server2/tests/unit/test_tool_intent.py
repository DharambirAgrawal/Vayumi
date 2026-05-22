from __future__ import annotations

from server.orchestrator.tool_intent import suggest_web_search_query


def test_suggest_news_question() -> None:
    q = suggest_web_search_query("What is latest going on in the news")
    assert q is not None
    assert "news" in q.lower()


def test_suggest_headlines() -> None:
    assert suggest_web_search_query("Any headlines from today?") is not None


def test_no_suggest_small_talk() -> None:
    assert suggest_web_search_query("Hello") is None
    assert suggest_web_search_query("Thanks") is None


def test_no_suggest_capability_only() -> None:
    assert suggest_web_search_query("Can you remember my name?") is None
