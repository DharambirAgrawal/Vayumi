from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from starlette.websockets import WebSocket

from server.logger import get_logger
from server.transport.outbound import send_json
from server.transport.protocol import (
    ClientControlCommand,
    ClientControlMessage,
    ClientControlPayload,
    ClientStatePayload,
)

log = get_logger("transport.client_control")

PlaybackState = Literal["idle", "playing", "paused"]
CaptureState = Literal["idle", "recording"]
SessionMode = Literal["conversation", "meeting"]


@dataclass
class ClientControlSession:
    """Tracks the client's last-reported audio/UI state for this WebSocket session."""

    playback: PlaybackState = "idle"
    capture: CaptureState = "idle"
    visible: bool = True
    route: Literal["speaker", "earpiece", "bluetooth", "none"] | None = None
    mode: SessionMode = "conversation"

    def handle_client_state(self, state: ClientStatePayload) -> None:
        self.playback = state.playback
        self.capture = state.capture
        self.visible = state.visible
        self.route = state.route
        log.debug(
            "client_state.updated",
            playback=self.playback,
            capture=self.capture,
            visible=self.visible,
            route=self.route,
        )

    def set_mode(self, mode: SessionMode) -> None:
        self.mode = mode
        log.info("client_mode.updated", mode=mode)


async def send_client_control(
    websocket: WebSocket,
    command: ClientControlCommand,
    reason: str,
    *,
    turn_id: str | None = None,
) -> None:
    message = ClientControlMessage(
        payload=ClientControlPayload(command=command, reason=reason, turn_id=turn_id),
    )
    await send_json(websocket, message)


async def send_interrupt_controls(
    websocket: WebSocket,
    *,
    turn_id: str | None,
    reason: str = "interrupt",
) -> None:
    await send_client_control(websocket, "stop", reason, turn_id=turn_id)
    await send_client_control(websocket, "clear_queue", reason, turn_id=turn_id)


async def send_tts_play_control(
    websocket: WebSocket,
    *,
    turn_id: str,
) -> None:
    await send_client_control(websocket, "play", "tts_start", turn_id=turn_id)


