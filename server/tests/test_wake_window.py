"""Tests for wake word and command-window behavior."""

from datetime import datetime, timedelta

from models import Session
from main import _strip_wake_word


def test_strip_wake_word_removes_common_variants():
    has_wake, cleaned = _strip_wake_word("Vayumi play music")
    assert has_wake is True
    assert cleaned == "play music"

    has_wake, cleaned = _strip_wake_word("Вайоми, what time is it?")
    assert has_wake is False
    assert cleaned == "Вайоми, what time is it?"


def test_session_wake_window_opens_and_expires():
    session = Session()
    session.open_wake_window(seconds=1)

    assert session.wake_word_active is True
    assert session.is_wake_window_open() is True

    session.wake_window_expires_at = datetime.utcnow() - timedelta(seconds=1)
    assert session.is_wake_window_open() is False

    session.close_wake_window()
    assert session.wake_word_active is False
    assert session.wake_window_expires_at is None