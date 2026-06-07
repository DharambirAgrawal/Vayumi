from __future__ import annotations

from server.orchestrator.tool_fallback import (
    answer_grounded_in_web_search,
    answer_looks_stale,
    fallback_web_search_query,
    is_insufficient_tool_answer,
    is_trivial_chat_followup,
    needs_web_search_synthesis,
    parse_inline_web_search_query,
    should_fallback_web_search,
    tool_status_while_searching,
)


def test_ack_only_model_output_triggers_fallback() -> None:
    assert should_fallback_web_search(
        model_content="Let me check that for you. Give me a moment.",
    )


def test_inline_web_search_tag_triggers_fallback() -> None:
    assert should_fallback_web_search(
        model_content='Sure. [web_search query="NVIDIA stock price"]',
    )
    assert (
        parse_inline_web_search_query('[web_search query="NVIDIA stock price"]')
        == "NVIDIA stock price"
    )
    assert (
        fallback_web_search_query(
            user_text="nvidia price",
            model_content='[web_search query="NVIDIA stock price"]',
        )
        == "NVIDIA stock price"
    )


def test_philosophy_answer_does_not_fallback() -> None:
    assert not should_fallback_web_search(
        model_content="I don't have access to real-time news. Would you like me to search?",
    )


def test_story_does_not_fallback() -> None:
    assert not should_fallback_web_search(
        model_content="Once upon a time in a quiet valley...",
    )


def test_insufficient_tool_answer_detects_ack_and_leak() -> None:
    assert is_insufficient_tool_answer("Let me check that for you.")
    assert is_insufficient_tool_answer(
        'Glad to help. [web_search query="NVIDIA stock price"]'
    )
    assert not is_insufficient_tool_answer(
        "NVIDIA is trading around $120 per share today."
    )


def test_hallucinated_price_triggers_fallback() -> None:
    model = (
        'Okay. [web_search query="nvidia stock price"] '
        "The current price is approximately $525.43."
    )
    assert should_fallback_web_search(model_content=model)
    assert not answer_grounded_in_web_search(model, [])
    assert needs_web_search_synthesis(model, [])


def test_tool_status_skips_stale_hallucination() -> None:
    stale = (
        "Ah, SpaceX's IPO is generating buzz. Currently slated for May 2024."
    )
    assert tool_status_while_searching(stale) == "Looking that up now."


def test_stale_year_triggers_resynthesis() -> None:
    stale = "The IPO is expected in May 2024 at an $80 billion valuation."
    assert answer_looks_stale(stale, today_year=2026)
    assert should_fallback_web_search(model_content=stale)
    assert needs_web_search_synthesis(stale, [])


def test_trivial_chat_followup() -> None:
    assert is_trivial_chat_followup("?")
    assert not is_trivial_chat_followup("what is nvidia stock price")
