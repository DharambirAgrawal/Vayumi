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
    """discard=true: client stopped capture for echo suppression, not a user utterance."""

    discard: bool = False


class AudioEndMessage(BaseModel):
    type: Literal["audio_end"] = "audio_end"
    payload: AudioEndPayload = AudioEndPayload()


class InterruptPayload(BaseModel):
    source: Literal["wake", "button", "voice"]


class InterruptMessage(BaseModel):
    type: Literal["interrupt"] = "interrupt"
    payload: InterruptPayload


class PingPayload(BaseModel):
    t: int


class PingMessage(BaseModel):
    type: Literal["ping"] = "ping"
    payload: PingPayload


class ClientStatePayload(BaseModel):
    playback: Literal["idle", "playing", "paused"]
    capture: Literal["idle", "recording"]
    visible: bool
    route: Literal["speaker", "earpiece", "bluetooth", "none"] | None = None


class ClientStateMessage(BaseModel):
    type: Literal["client_state"] = "client_state"
    payload: ClientStatePayload


class ModePayload(BaseModel):
    mode: Literal["conversation", "meeting"]


class ModeMessage(BaseModel):
    type: Literal["mode"] = "mode"
    payload: ModePayload


ClientMessage = Annotated[
    HelloMessage
    | ChatMessage
    | AudioStartMessage
    | AudioEndMessage
    | InterruptMessage
    | PingMessage
    | ClientStateMessage
    | ModeMessage,
    Field(discriminator="type"),
]


# ── Server → Client ─────────────────────────────────────


class WelcomePayload(BaseModel):
    session_id: str
    server_version: str = "0.1.0"
    resumed: bool = False
    task_board_snapshot: dict[str, object] | None = None


class WelcomeMessage(BaseModel):
    type: Literal["welcome"] = "welcome"
    payload: WelcomePayload


class EchoPayload(BaseModel):
    kind: str
    payload: dict[str, Any]


class EchoMessage(BaseModel):
    type: Literal["echo"] = "echo"
    payload: EchoPayload


class CaptionPayload(BaseModel):
    text: str
    partial: bool
    turn_id: str = ""


class CaptionMessage(BaseModel):
    type: Literal["caption"] = "caption"
    payload: CaptionPayload


class ServerAudioStartPayload(BaseModel):
    sample_rate: int = 16000
    format: str = "pcm_s16le"
    turn_id: str


class ServerAudioStartMessage(BaseModel):
    type: Literal["audio_start"] = "audio_start"
    payload: ServerAudioStartPayload


class ServerAudioEndPayload(BaseModel):
    turn_id: str
    interrupted: bool = False
    error: bool = False


class UserMessagePayload(BaseModel):
    """STT or server-confirmed user text for the chat thread (voice turns)."""

    text: str
    turn_id: str
    source: Literal["voice", "chat"] = "voice"


class UserMessage(BaseModel):
    type: Literal["user_message"] = "user_message"
    payload: UserMessagePayload


class AssistantChatMessagePayload(BaseModel):
    text: str
    turn_id: str
    final: bool = True


class AssistantChatMessage(BaseModel):
    type: Literal["chat_message"] = "chat_message"
    payload: AssistantChatMessagePayload


class ServerAudioEndMessage(BaseModel):
    type: Literal["audio_end"] = "audio_end"
    payload: ServerAudioEndPayload


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


ClientControlCommand = Literal[
    "play",
    "pause",
    "stop",
    "duck",
    "unduck",
    "clear_queue",
    "start_capture",
    "stop_capture",
]


class ClientControlPayload(BaseModel):
    command: ClientControlCommand
    reason: str
    turn_id: str | None = None


class ClientControlMessage(BaseModel):
    type: Literal["client_control"] = "client_control"
    payload: ClientControlPayload


class EventPayload(BaseModel):
    kind: Literal[
        "tool_started",
        "tool_done",
        "task_step",
        "task_done",
        "task_error",
        "file_processing",
        "session_superseded",
    ]
    task_id: str
    summary: str


class EventMessage(BaseModel):
    type: Literal["event"] = "event"
    payload: EventPayload


ServerMessage = (
    WelcomeMessage
    | EchoMessage
    | CaptionMessage
    | UserMessage
    | AssistantChatMessage
    | ServerAudioStartMessage
    | ServerAudioEndMessage
    | ClientControlMessage
    | EventMessage
    | PongMessage
    | ErrorMessage
)


# ── Helpers ──────────────────────────────────────────────

_client_msg_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


def parse_client_message(raw: str) -> ClientMessage:
    return _client_msg_adapter.validate_json(raw)


def serialize_server_message(message: ServerMessage) -> str:
    return message.model_dump_json()
