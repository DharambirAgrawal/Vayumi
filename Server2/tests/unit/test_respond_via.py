from __future__ import annotations

from server.transport.client_control import ClientControlSession
from server.voice.respond_via import compute_respond_via


def test_voice_always_voice_and_chat_replace() -> None:
    cc = ClientControlSession()
    d = compute_respond_via(capabilities_tts=True, client_state=cc, input_kind="voice")
    assert d.respond_via == "voice_and_chat"
    assert d.interrupt_policy == "replace"


def test_chat_defaults_voice_when_capable() -> None:
    cc = ClientControlSession()
    d = compute_respond_via(capabilities_tts=True, client_state=cc, input_kind="chat")
    assert d.respond_via == "voice_and_chat"
    assert d.interrupt_policy == "queue"


def test_chat_no_tts_capability() -> None:
    cc = ClientControlSession()
    d = compute_respond_via(capabilities_tts=False, client_state=cc, input_kind="chat")
    assert d.respond_via == "chat_only"


def test_chat_blocked_while_playing() -> None:
    cc = ClientControlSession(playback="playing")
    d = compute_respond_via(capabilities_tts=True, client_state=cc, input_kind="chat")
    assert d.respond_via == "chat_only"


def test_chat_backgrounded() -> None:
    cc = ClientControlSession(visible=False)
    d = compute_respond_via(capabilities_tts=True, client_state=cc, input_kind="chat")
    assert d.respond_via == "chat_only"


def test_proactive_needs_info_visible() -> None:
    cc = ClientControlSession(visible=True, capture="idle")
    d = compute_respond_via(capabilities_tts=True, client_state=cc, input_kind="proactive")
    assert d.respond_via == "voice_and_chat"
