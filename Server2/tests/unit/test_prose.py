from server.orchestrator.prose import (
    finalize_assistant_prose,
    sanitize_spoken_prose,
    texts_largely_repeat,
)


def test_finalize_collapses_markdown_echo_block() -> None:
    answer = (
        "I'm doing well, thank you for asking! It's nice to hear from you. "
        "How are you doing today?"
    )
    raw = answer + "\n\n```\n" + answer + "\n```"
    assert finalize_assistant_prose(raw) == answer


def test_finalize_keeps_distinct_follow_up() -> None:
    text = "First point.\n\nSecond point adds new information."
    assert finalize_assistant_prose(text) == text


def test_finalize_strips_raw_urls() -> None:
    raw = (
        "NVDA is around $219. "
        "[https://investor.nvidia.com/stock-info/default.aspx]"
    )
    assert "http" not in finalize_assistant_prose(raw)
    assert "$219" in finalize_assistant_prose(raw)


def test_sanitize_collapses_trailing_bang_after_period() -> None:
    assert sanitize_spoken_prose("Busy day.!") == "Busy day."


def test_texts_largely_repeat_detects_paraphrase() -> None:
    a = "I'm doing well, thank you for asking!"
    b = "I'm doing well, thank you for asking! It's nice to hear from you."
    assert texts_largely_repeat(a, b)
