from __future__ import annotations

from pathlib import Path

from server.tools.page_extract import extract_article_text

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "html"


def test_extract_news_article_trafilatura_or_fallback() -> None:
    html = (FIXTURES / "news_article.html").read_text(encoding="utf-8")
    text, method = extract_article_text(html, "https://news.example/a", min_useful_chars=100)
    assert method in ("trafilatura", "fallback", "fallback_short")
    assert "NVIDIA" in text
    assert "GPU" in text or "data-center" in text


def test_extract_wiki_style() -> None:
    html = (FIXTURES / "wiki_style.html").read_text(encoding="utf-8")
    text, method = extract_article_text(
        html, "https://en.wikipedia.org/wiki/Mars", min_useful_chars=50
    )
    assert text
    assert "Mars" in text
    assert method != "empty"


def test_extract_thin_shell_mostly_empty() -> None:
    html = (FIXTURES / "thin_shell.html").read_text(encoding="utf-8")
    text, method = extract_article_text(html, "https://spa.example/", min_useful_chars=400)
    assert len(text) < 400
    assert method in ("empty", "fallback_short", "fallback")
