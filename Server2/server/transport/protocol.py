from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

# ── Client → Server ─────────────────────────────────────


class HelloPayload(BaseModel):
    client: Literal["web", "ios", "android", "esp32"]
    capabilities: dict[str, bool] = {}
    session_id: str | None = None


class HelloMessage(BaseModel):
    type: Literal["hello"] = "hello"
    payload: HelloPayload


class ChatPayload(BaseModel):
    text: str
    attachments: list[dict[str, Any]] = []


class ChatMessage(BaseModel):
    type: Literal["chat"] = "chat"
    payload: ChatPayload


class AudioStartPayload(BaseModel):
    sample_rate: int = 16000
    format: str = "pcm_s16le"


class AudioStartMessage(BaseModel):
    type: Literal["audio_start"] = "audio_start"
    payload: AudioStartPayload


class AudioEndPayload(BaseModel):
    pass


class AudioEndMessage(BaseModel):
    type: Literal["audio_end"] = "audio_end"
    payload: AudioEndPayload = AudioEndPayload()


class PingPayload(BaseModel):
    t: int


class PingMessage(BaseModel):
    type: Literal["ping"] = "ping"
    payload: PingPayload


ClientMessage = Annotated[
    HelloMessage | ChatMessage | AudioStartMessage | AudioEndMessage | PingMessage,
    Field(discriminator="type"),
]


# ── Server → Client ─────────────────────────────────────


class WelcomePayload(BaseModel):
    session_id: str
    server_version: str = "0.1.0"


class WelcomeMessage(BaseModel):
    type: Literal["welcome"] = "welcome"
    payload: WelcomePayload


class EchoPayload(BaseModel):
    kind: str
    payload: dict[str, Any]


class EchoMessage(BaseModel):
    type: Literal["echo"] = "echo"
    payload: EchoPayload


class PongPayload(BaseModel):
    t: int


class PongMessage(BaseModel):
    type: Literal["pong"] = "pong"
    payload: PongPayload


class ErrorPayload(BaseModel):
    code: int
    message: str


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    payload: ErrorPayload


ServerMessage = WelcomeMessage | EchoMessage | PongMessage | ErrorMessage


# ── Helpers ──────────────────────────────────────────────

_client_msg_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


def parse_client_message(raw: str) -> ClientMessage:
    return _client_msg_adapter.validate_json(raw)


def serialize_server_message(message: ServerMessage) -> str:
    return message.model_dump_json()
