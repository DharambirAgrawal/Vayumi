from __future__ import annotations

from server.orchestrator.supervisor import Supervisor
from server.transport.session_registry import UserSession
from server.transport.session_busy import session_busy


def test_session_busy_thinking() -> None:
    session = UserSession(
        user_id="u",
        session_id="s",
        supervisor=Supervisor(user_id="u", session_id="s"),
    )
    session.interrupt.begin_thinking("t1")
    assert session_busy(session)
