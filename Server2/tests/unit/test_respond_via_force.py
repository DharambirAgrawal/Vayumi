from __future__ import annotations

from server.transport.client_control import ClientControlSession
from server.voice.respond_via import compute_respond_via


def test_force_voice_overrides_playback_playing() -> None:
    state = ClientControlSession(
        playback="playing",
        capture="idle",
        visible=True,
        route="speaker",
        mode="conversation",
    )
    decision = compute_respond_via(
        capabilities_tts=True,
        client_state=state,
        input_kind="chat",
        force_voice=True,
    )
    assert decision.respond_via == "voice_and_chat"
