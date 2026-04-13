from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
import base64

import pytest
from starlette.websockets import WebSocketState

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import main as server_main
from auth import UserRecord
from models import ClientType, Session


class _FakeWebSocket:
    def __init__(self, receive_events: list[dict], ready_message: dict | None = None):
        self.client_state = WebSocketState.CONNECTING
        self._receive_events = list(receive_events)
        self._ready_message = ready_message or {"type": "client_ready", "client_type": "web", "capabilities": []}
        self.sent_json: list[dict] = []
        self.closed = False

    async def accept(self):
        self.client_state = WebSocketState.CONNECTED

    async def close(self, code: int = 1000, reason: str | None = None):
        self.closed = True
        self.client_state = WebSocketState.DISCONNECTED

    async def send_json(self, data: dict):
        self.sent_json.append(data)

    async def receive_json(self):
        return self._ready_message

    async def receive(self):
        if self._receive_events:
            return self._receive_events.pop(0)
        return {"type": "websocket.disconnect"}


class _FakeSessionManager:
    def __init__(self, session: Session):
        self.session = session

    async def create_session(self):
        return self.session

    async def register_client(self, session_id, client_type, capabilities, audio_config):
        if client_type == ClientType.WEB:
            self.session.active_voice_source = ClientType.WEB
        return self.session

    async def get_session(self, session_id):
        return self.session

    async def unregister_client(self, session_id, client_type):
        return self.session

    async def get_active_sessions_count(self):
        return 1


class _AudioPipelineSpy:
    def __init__(self):
        self.processed = 0

    async def process_chunk(self, session_id, chunk):
        self.processed += 1
        return None


@pytest.fixture(autouse=True)
def _reset_server_globals():
    server_main.active_response_tasks.clear()
    server_main.active_websockets.clear()
    server_main.session_owner_map.clear()
    server_main.live_wake_interrupt_buffers.clear()
    server_main.live_wake_interrupt_checked_bytes.clear()
    server_main.meeting_audio_accumulators.clear()
    yield
    server_main.active_response_tasks.clear()
    server_main.active_websockets.clear()
    server_main.session_owner_map.clear()
    server_main.live_wake_interrupt_buffers.clear()
    server_main.live_wake_interrupt_checked_bytes.clear()
    server_main.meeting_audio_accumulators.clear()


@pytest.mark.asyncio
async def test_websocket_multi_message_control_and_interrupt(monkeypatch):
    session = Session(session_id="ws-session-1")
    manager = _FakeSessionManager(session)
    server_main.session_manager = manager
    server_main.audio_pipeline = _AudioPipelineSpy()

    async def _fake_require_user(websocket):
        return UserRecord(id="u1", email="u1@example.com", name="User")

    monkeypatch.setattr(server_main, "_require_ws_user", _fake_require_user)

    calls: list[tuple[str, str, str]] = []

    def _fake_start(websocket, sess, transcript, respond_via="chat_only", interrupt_policy="queue"):
        calls.append(("start", transcript, interrupt_policy))

    async def _fake_interrupt(websocket, sess, trigger="unknown"):
        calls.append(("interrupt", trigger, ""))

    monkeypatch.setattr(server_main, "_start_agent_response_with_policy", _fake_start)
    monkeypatch.setattr(server_main, "_interrupt_active_response", _fake_interrupt)

    events = [
        {"text": json.dumps({"type": "chatbot_message", "text": "first", "interrupt_policy": "queue"})},
        {"text": json.dumps({"type": "chatbot_message", "text": "second", "interrupt_policy": "queue"})},
        {"text": json.dumps({"type": "interrupt", "trigger": "manual", "wake_confidence": 0.95})},
        {"type": "websocket.disconnect"},
    ]
    ws = _FakeWebSocket(events)

    await server_main._run_websocket_session(ws, ClientType.WEB)

    assert ("start", "first", "queue") in calls
    assert ("start", "second", "queue") in calls
    assert ("interrupt", "manual", "") in calls
    assert any(msg.get("type") == "session_started" for msg in ws.sent_json)


@pytest.mark.asyncio
async def test_websocket_midstream_interrupt_race_with_synthetic_chunks(monkeypatch):
    session = Session(session_id="ws-session-2")
    session.is_ai_speaking = True
    manager = _FakeSessionManager(session)
    audio_spy = _AudioPipelineSpy()

    server_main.session_manager = manager
    server_main.audio_pipeline = audio_spy

    async def _fake_require_user(websocket):
        return UserRecord(id="u2", email="u2@example.com", name="User")

    monkeypatch.setattr(server_main, "_require_ws_user", _fake_require_user)

    seen_chunks: list[bytes] = []

    async def _fake_live_interrupt(websocket, sess, session_id, chunk):
        seen_chunks.append(chunk)
        return True

    monkeypatch.setattr(server_main, "_maybe_detect_live_wake_interrupt", _fake_live_interrupt)

    events = [
        {"bytes": b"\x01\x02" * 500},
        {"bytes": b"\x03\x04" * 500},
        {"type": "websocket.disconnect"},
    ]
    ws = _FakeWebSocket(events)

    await server_main._run_websocket_session(ws, ClientType.WEB)

    assert len(seen_chunks) == 2
    # Bytes are consumed by live interrupt checks, so normal audio processing is skipped.
    assert audio_spy.processed == 0


@pytest.mark.asyncio
async def test_websocket_chatbot_message_preserves_attachments(monkeypatch):
    session = Session(session_id="ws-session-attachments")
    manager = _FakeSessionManager(session)
    server_main.session_manager = manager

    async def _fake_require_user(websocket):
        return UserRecord(id="u3", email="u3@example.com", name="User")

    monkeypatch.setattr(server_main, "_require_ws_user", _fake_require_user)

    monkeypatch.setattr(server_main, "external_read_url", lambda url: json.dumps({"url": url, "summary": "link summary"}))
    monkeypatch.setattr(server_main, "external_analyze_image", lambda data: json.dumps({"summary": "image summary"}))
    monkeypatch.setattr(server_main, "external_analyze_video", lambda data: json.dumps({"summary": "video summary"}))

    captured: list[tuple[str, list[dict]]] = []

    def _fake_start(websocket, sess, transcript, respond_via="chat_only", interrupt_policy="queue"):
        captured.append((transcript, list(getattr(sess, "attachments", []))))

    monkeypatch.setattr(server_main, "_start_agent_response_with_policy", _fake_start)

    websocket = _FakeWebSocket([])
    message = {
        "type": "chatbot_message",
        "text": "Check this link and image",
        "attachments": [
            {"type": "link", "url": "https://example.com/post", "download": False},
            {"type": "image", "data": base64.b64encode(b"image-bytes").decode("ascii"), "mime_type": "image/png"},
            {"type": "video", "data": base64.b64encode(b"video-bytes").decode("ascii"), "mime_type": "video/mp4"},
        ],
    }

    await server_main._handle_control_message(session.session_id, message, websocket, session)

    assert len(session.attachments) == 3
    assert session.attachments[0]["type"] == "link"
    assert session.attachments[1]["type"] == "image"
    assert session.attachments[2]["type"] == "video"
    assert captured and captured[0][0].startswith("Check this link and image")
    assert "link summary" in captured[0][0]
    assert "image summary" in captured[0][0]
    assert "video summary" in captured[0][0]


@pytest.mark.asyncio
async def test_websocket_chatbot_message_includes_audio_attachment_context(monkeypatch):
    session = Session(session_id="ws-session-audio-attachments")
    manager = _FakeSessionManager(session)
    server_main.session_manager = manager

    async def _fake_require_user(websocket):
        return UserRecord(id="u4", email="u4@example.com", name="User")

    monkeypatch.setattr(server_main, "_require_ws_user", _fake_require_user)
    monkeypatch.setattr(server_main, "external_transcribe_audio", lambda data: json.dumps({"transcript": "audio transcript"}))

    captured: list[str] = []

    def _fake_start(websocket, sess, transcript, respond_via="chat_only", interrupt_policy="queue"):
        captured.append(transcript)

    monkeypatch.setattr(server_main, "_start_agent_response_with_policy", _fake_start)

    message = {
        "type": "chatbot_message",
        "text": "Check the recording",
        "attachments": [
            {"type": "audio", "data": base64.b64encode(b"audio-bytes").decode("ascii"), "mime_type": "audio/wav"},
        ],
    }

    await server_main._handle_control_message(session.session_id, message, _FakeWebSocket([]), session)

    assert len(session.attachments) == 1
    assert session.attachments[0]["type"] == "audio"
    assert captured and "audio transcript" in captured[0]


@pytest.mark.asyncio
async def test_websocket_resume_and_resume_policy_validation(monkeypatch):
    session = Session(session_id="ws-session-resume")
    session.pending_resume_words = ["resume", "from", "here"]
    manager = _FakeSessionManager(session)
    server_main.session_manager = manager

    async def _fake_require_user(websocket):
        return UserRecord(id="u5", email="u5@example.com", name="User")

    monkeypatch.setattr(server_main, "_require_ws_user", _fake_require_user)

    captured: list[tuple[str, str, str]] = []

    def _fake_start(websocket, sess, transcript, respond_via="chat_only", interrupt_policy="queue"):
        captured.append((transcript, respond_via, interrupt_policy))

    monkeypatch.setattr(server_main, "_start_agent_response_with_policy", _fake_start)

    websocket = _FakeWebSocket([])
    websocket.client_state = WebSocketState.CONNECTED

    await server_main._handle_control_message(
        session.session_id,
        {"type": "resume_response"},
        websocket,
        session,
    )
    await server_main._handle_control_message(
        session.session_id,
        {"type": "set_resume_policy", "policy": "bad_policy"},
        websocket,
        session,
    )

    assert captured == [("resume from here", "voice_and_chat", "replace")]
    assert session.pending_resume_words == []
    assert any(msg.get("code") == "invalid_resume_policy" for msg in websocket.sent_json)


@pytest.mark.asyncio
async def test_websocket_requires_client_ready_after_hello(monkeypatch):
    session = Session(session_id="ws-session-protocol")
    manager = _FakeSessionManager(session)
    server_main.session_manager = manager
    server_main.audio_pipeline = _AudioPipelineSpy()

    async def _fake_require_user(websocket):
        return UserRecord(id="u6", email="u6@example.com", name="User")

    monkeypatch.setattr(server_main, "_require_ws_user", _fake_require_user)

    ws = _FakeWebSocket([], ready_message={"type": "chatbot_message", "text": "oops"})

    await server_main._run_websocket_session(ws, ClientType.WEB)

    assert any(msg.get("code") == "protocol_error" for msg in ws.sent_json)
    assert ws.closed is True
