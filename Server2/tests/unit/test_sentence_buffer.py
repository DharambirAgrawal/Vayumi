from __future__ import annotations

from server.voice.sentence_buffer import drain_complete_sentences


def test_drain_sentences_incremental() -> None:
    buffer = "Hello there. How are"
    sentences, remainder = drain_complete_sentences(buffer)
    assert sentences == ["Hello there."]
    assert remainder == "How are"

    more, remainder = drain_complete_sentences(remainder + " you? Fine!")
    assert more == ["How are you?"]
    assert remainder == "Fine!"


def test_drain_no_boundary_yet() -> None:
    sentences, remainder = drain_complete_sentences("Still going")
    assert sentences == []
    assert remainder == "Still going"
