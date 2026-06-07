from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.transport.session_registry import UserSession

# Client playback state can lag behind server TTS completion.
_PLAYBACK_GRACE_S = 3.0


def session_busy(session: UserSession) -> bool:
    return session.interrupt.state.value in ("speaking", "thinking")


def playback_blocks_voice(session: UserSession) -> bool:
    """True while client audio is likely still playing (incl. post-TTS grace)."""
    if session.client_control.playback == "playing":
        return True
    if session.turn_task is not None and not session.turn_task.done():
        return True
    if session.last_turn_completed_at is not None:
        elapsed = time.monotonic() - session.last_turn_completed_at
        if elapsed < _PLAYBACK_GRACE_S:
            return True
    return False


def chat_should_queue(session: UserSession, *, interrupt_policy: str) -> bool:
    if interrupt_policy != "queue":
        return False
    if session_busy(session):
        return True
    if playback_blocks_voice(session):
        return True
    return False
