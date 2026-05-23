from __future__ import annotations

import json

import pytest

from server.transport.protocol import (
    AssistantChatMessage,
    AssistantChatMessagePayload,
    AudioEndMessage,
    AudioStartMessage,
    CaptionMessage,
    CaptionPayload,
    ChatMessage,
    ClientControlMessage,
    ClientControlPayload,
    ClientStateMessage,
    EchoMessage,
    EchoPayload,
    ErrorMessage,
    ErrorPayload,
    EventMessage,
    EventPayload,
    HelloMessage,
    InterruptMessage,
    ModeMessage,
    PingMessage,
    PongMessage,
    PongPayload,
    ServerAudioEndMessage,
    ServerAudioEndPayload,
    ServerAudioStartMessage,
    ServerAudioStartPayload,
    UserMessage,
    UserMessagePayload,
    WelcomeMessage,
    WelcomePayload,
    parse_client_message,
    serialize_server_message,
)


class TestParseClientMessage:
    def test_hello(self) -> None:
        raw = json.dumps({
            "type": "hello",
            "payload": {
                "client": "web",
                "capabilities": {"aec": False, "vad": True, "wake": False},
            },
        })
        msg = parse_client_message(raw)
        assert isinstance(msg, HelloMessage)
        assert msg.payload.client == "web"
        assert msg.payload.capabilities["vad"] is True

    def test_hello_with_session_id(self) -> None:
        raw = json.dumps({
            "type": "hello",
            "payload": {"client": "ios", "session_id": "s_123"},
        })
        msg = parse_client_message(raw)
        assert isinstance(msg, HelloMessage)
        assert msg.payload.session_id == "s_123"

    def test_chat(self) -> None:
        raw = json.dumps({"type": "chat", "payload": {"text": "hello world"}})
        msg = parse_client_message(raw)
        assert isinstance(msg, ChatMessage)
        assert msg.payload.text == "hello world"
        assert msg.payload.attachments == []

    def test_chat_with_attachments(self) -> None:
        raw = json.dumps({
            "type": "chat",
            "payload": {
                "text": "here is a file",
                "attachments": [{"file_id": "f1", "kind": "image", "mime": "image/png"}],
            },
        })
        msg = parse_client_message(raw)
        assert isinstance(msg, ChatMessage)
        assert len(msg.payload.attachments) == 1
        assert msg.payload.attachments[0]["file_id"] == "f1"

    def test_audio_start(self) -> None:
        raw = json.dumps({
            "type": "audio_start",
            "payload": {"sample_rate": 16000, "format": "pcm_s16le"},
        })
        msg = parse_client_message(raw)
        assert isinstance(msg, AudioStartMessage)
        assert msg.payload.sample_rate == 16000

    def test_audio_end(self) -> None:
        raw = json.dumps({"type": "audio_end", "payload": {}})
        msg = parse_client_message(raw)
        assert isinstance(msg, AudioEndMessage)

    def test_ping(self) -> None:
        raw = json.dumps({"type": "ping", "payload": {"t": 1234567890}})
        msg = parse_client_message(raw)
        assert isinstance(msg, PingMessage)
        assert msg.payload.t == 1234567890

    def test_interrupt(self) -> None:
        raw = json.dumps({"type": "interrupt", "payload": {"source": "button"}})
        msg = parse_client_message(raw)
        assert isinstance(msg, InterruptMessage)
        assert msg.payload.source == "button"

    def test_client_state(self) -> None:
        raw = json.dumps({
            "type": "client_state",
            "payload": {
                "playback": "idle",
                "capture": "recording",
                "visible": True,
            },
        })
        msg = parse_client_message(raw)
        assert isinstance(msg, ClientStateMessage)
        assert msg.payload.capture == "recording"

    def test_mode(self) -> None:
        raw = json.dumps({"type": "mode", "payload": {"mode": "conversation"}})
        msg = parse_client_message(raw)
        assert isinstance(msg, ModeMessage)
        assert msg.payload.mode == "conversation"

    def test_invalid_type_raises(self) -> None:
        raw = json.dumps({"type": "unknown_type", "payload": {}})
        with pytest.raises(Exception):
            parse_client_message(raw)

    def test_missing_type_raises(self) -> None:
        raw = json.dumps({"payload": {"text": "hi"}})
        with pytest.raises(Exception):
            parse_client_message(raw)

    def test_malformed_json_raises(self) -> None:
        with pytest.raises(Exception):
            parse_client_message("{not json}")

    def test_invalid_client_type_raises(self) -> None:
        raw = json.dumps({
            "type": "hello",
            "payload": {"client": "gameboy"},
        })
        with pytest.raises(Exception):
            parse_client_message(raw)


class TestSerializeServerMessage:
    def test_welcome(self) -> None:
        msg = WelcomeMessage(
            payload=WelcomePayload(
                session_id="s_1",
                resumed=True,
                task_board_snapshot={"tasks": []},
            ),
        )
        raw = serialize_server_message(msg)
        data = json.loads(raw)
        assert data["type"] == "welcome"
        assert data["payload"]["session_id"] == "s_1"
        assert data["payload"]["resumed"] is True
        assert data["payload"]["task_board_snapshot"] == {"tasks": []}

    def test_chat_message(self) -> None:
        msg = AssistantChatMessage(
            payload=AssistantChatMessagePayload(
                text="full reply",
                turn_id="t1",
                final=True,
            ),
        )
        raw = serialize_server_message(msg)
        data = json.loads(raw)
        assert data["type"] == "chat_message"
        assert data["payload"]["final"] is True

    def test_user_message(self) -> None:
        msg = UserMessage(
            payload=UserMessagePayload(
                text="how are you",
                turn_id="t1",
                source="voice",
            ),
        )
        data = json.loads(serialize_server_message(msg))
        assert data["type"] == "user_message"
        assert data["payload"]["source"] == "voice"

    def test_client_control_capture_commands(self) -> None:
        for cmd in ("start_capture", "stop_capture"):
            msg = ClientControlMessage(
                payload=ClientControlPayload(command=cmd, reason="tts"),
            )
            data = json.loads(serialize_server_message(msg))
            assert data["payload"]["command"] == cmd

    def test_echo(self) -> None:
        msg = EchoMessage(
            payload=EchoPayload(kind="chat", payload={"text": "hello"}),
        )
        raw = serialize_server_message(msg)
        data = json.loads(raw)
        assert data["type"] == "echo"
        assert data["payload"]["kind"] == "chat"
        assert data["payload"]["payload"]["text"] == "hello"

    def test_caption(self) -> None:
        msg = CaptionMessage(payload=CaptionPayload(text="hello", partial=True))
        raw = serialize_server_message(msg)
        data = json.loads(raw)
        assert data["type"] == "caption"
        assert data["payload"]["text"] == "hello"
        assert data["payload"]["partial"] is True

    def test_server_audio_start(self) -> None:
        msg = ServerAudioStartMessage(
            payload=ServerAudioStartPayload(turn_id="turn-1"),
        )
        raw = serialize_server_message(msg)
        data = json.loads(raw)
        assert data["type"] == "audio_start"
        assert data["payload"]["turn_id"] == "turn-1"
        assert data["payload"]["sample_rate"] == 24000

    def test_server_audio_end(self) -> None:
        msg = ServerAudioEndMessage(payload=ServerAudioEndPayload(turn_id="turn-1"))
        raw = serialize_server_message(msg)
        data = json.loads(raw)
        assert data["type"] == "audio_end"
        assert data["payload"]["turn_id"] == "turn-1"

    def test_pong(self) -> None:
        msg = PongMessage(payload=PongPayload(t=999))
        raw = serialize_server_message(msg)
        data = json.loads(raw)
        assert data["type"] == "pong"
        assert data["payload"]["t"] == 999

    def test_error(self) -> None:
        msg = ErrorMessage(payload=ErrorPayload(code=4400, message="bad"))
        raw = serialize_server_message(msg)
        data = json.loads(raw)
        assert data["type"] == "error"
        assert data["payload"]["code"] == 4400

    def test_client_control(self) -> None:
        msg = ClientControlMessage(
            payload=ClientControlPayload(command="stop", reason="interrupt"),
        )
        raw = serialize_server_message(msg)
        data = json.loads(raw)
        assert data["type"] == "client_control"
        assert data["payload"]["command"] == "stop"

    def test_event(self) -> None:
        msg = EventMessage(
            payload=EventPayload(kind="task_step", task_id="t1", summary="Searching"),
        )
        raw = serialize_server_message(msg)
        data = json.loads(raw)
        assert data["type"] == "event"
        assert data["payload"]["kind"] == "task_step"

    def test_session_superseded_event(self) -> None:
        msg = EventMessage(
            payload=EventPayload(
                kind="session_superseded",
                task_id="",
                summary="new_device",
            ),
        )
        data = json.loads(serialize_server_message(msg))
        assert data["payload"]["kind"] == "session_superseded"


class TestRoundTrip:
    """Parse a raw JSON string and verify we can serialize the echo back."""

    def test_chat_roundtrip(self) -> None:
        raw = json.dumps({"type": "chat", "payload": {"text": "roundtrip test"}})
        msg = parse_client_message(raw)
        assert isinstance(msg, ChatMessage)
        echo = EchoMessage(
            payload=EchoPayload(kind="chat", payload=msg.payload.model_dump()),
        )
        out = json.loads(serialize_server_message(echo))
        assert out["payload"]["payload"]["text"] == "roundtrip test"

    def test_ping_pong_roundtrip(self) -> None:
        raw = json.dumps({"type": "ping", "payload": {"t": 42}})
        msg = parse_client_message(raw)
        assert isinstance(msg, PingMessage)
        pong = PongMessage(payload=PongPayload(t=msg.payload.t))
        out = json.loads(serialize_server_message(pong))
        assert out["payload"]["t"] == 42
