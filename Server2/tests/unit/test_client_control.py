from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from server.transport.client_control import ClientControlSession, send_client_control
from server.transport.protocol import (
    ClientControlMessage,
    ClientStateMessage,
    ClientStatePayload,
    ModeMessage,
    parse_client_message,
    serialize_server_message,
)


class TestClientStateProtocol:
    def test_parse_client_state(self) -> None:
        raw = json.dumps({
            "type": "client_state",
            "payload": {
                "playback": "playing",
                "capture": "idle",
                "visible": True,
                "route": "speaker",
            },
        })
        msg = parse_client_message(raw)
        assert isinstance(msg, ClientStateMessage)
        assert msg.payload.playback == "playing"
        assert msg.payload.route == "speaker"

    def test_parse_mode(self) -> None:
        raw = json.dumps({"type": "mode", "payload": {"mode": "meeting"}})
        msg = parse_client_message(raw)
        assert isinstance(msg, ModeMessage)
        assert msg.payload.mode == "meeting"

    def test_serialize_client_control(self) -> None:
        msg = ClientControlMessage.model_validate({
            "type": "client_control",
            "payload": {
                "command": "stop",
                "reason": "interrupt",
                "turn_id": "t-1",
            },
        })
        data = json.loads(serialize_server_message(msg))
        assert data["type"] == "client_control"
        assert data["payload"]["command"] == "stop"
        assert data["payload"]["turn_id"] == "t-1"

    def test_invalid_playback_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClientStatePayload(playback="boom", capture="idle", visible=True)


class TestClientControlSession:
    def test_handle_client_state_updates_snapshot(self) -> None:
        session = ClientControlSession()
        state = ClientStatePayload(
            playback="paused",
            capture="recording",
            visible=False,
            route="bluetooth",
        )
        session.handle_client_state(state)
        assert session.playback == "paused"
        assert session.capture == "recording"
        assert session.visible is False
        assert session.route == "bluetooth"

    def test_set_mode(self) -> None:
        session = ClientControlSession()
        session.set_mode("meeting")
        assert session.mode == "meeting"


class TestSendClientControl:
    @pytest.mark.asyncio
    async def test_send_client_control(self) -> None:
        from starlette.websockets import WebSocketState

        sent: list[str] = []

        class FakeWebSocket:
            client_state = WebSocketState.CONNECTED

            async def send_text(self, data: str) -> None:
                sent.append(data)

        ws = FakeWebSocket()

        await send_client_control(ws, "clear_queue", "interrupt", turn_id="abc")
        assert len(sent) == 1
        payload = json.loads(sent[0])
        assert payload["type"] == "client_control"
        assert payload["payload"]["command"] == "clear_queue"
