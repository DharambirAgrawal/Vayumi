from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketState

from server.transport.session_registry import clear_registry_for_tests, enforce_session_singleton


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.client_state = WebSocketState.CONNECTED
    ws.send_text = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_second_connection_supersedes_first(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.orchestrator import supervisor as sup_mod

    async def noop_session(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(sup_mod, "load_or_create_session", noop_session)

    ws1 = _mock_ws()
    ws2 = _mock_ws()

    await enforce_session_singleton(
        user_id="u1",
        session_id="s1",
        new_ws=ws1,  # type: ignore[arg-type]
        hello_session_id=None,
    )
    session, resumed = await enforce_session_singleton(
        user_id="u1",
        session_id="s1",
        new_ws=ws2,  # type: ignore[arg-type]
        hello_session_id=None,
    )

    assert resumed is True
    assert session.websocket is ws2
    ws1.send_text.assert_called()
    sent = json.loads(ws1.send_text.call_args[0][0])
    assert sent["type"] == "event"
    assert sent["payload"]["kind"] == "session_superseded"
    ws1.close.assert_called_once()
    assert ws1.close.call_args.kwargs.get("code") == 4001 or ws1.close.call_args[0][0] == 4001


@pytest.mark.asyncio
async def test_first_connection_not_resumed(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.orchestrator import supervisor as sup_mod

    async def noop_session(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(sup_mod, "load_or_create_session", noop_session)

    ws = _mock_ws()
    _, resumed = await enforce_session_singleton(
        user_id="u2",
        session_id="s2",
        new_ws=ws,  # type: ignore[arg-type]
        hello_session_id=None,
    )
    assert resumed is False
