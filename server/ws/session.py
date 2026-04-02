# =============================================================================
# server/ws/session.py — Session Object & Factory
# =============================================================================
#
# PURPOSE:
#   Defines the Session class that holds ALL state for a single WebSocket
#   connection. Each connection gets exactly one Session, bound to one user_id.
#   Session state lives in-memory (Python dict Phase 1, Redis Phase 2).
#
# SESSION CLASS FIELDS:
#   session_id: str             — Unique session identifier (uuid4)
#   user_id: str                — Authenticated user this session belongs to
#   websocket: WebSocket        — The active FastAPI WebSocket connection
#   client_type: str            — "browser" | "esp32" | "mobile"
#   active_speaker: str         — Current speaker persona_id (default: user_id)
#   mode: str                   — Current mode: "normal" | "meeting" | "focus"
#   working_memory: list[dict]  — Current conversation turns
#                                  Each entry: {"role":"user"|"assistant", "text":str, "speaker":str}
#   task_state: dict            — {"status":"idle"} or {"status":"running","task_id":str,"started_at":float}
#   input_queue: list[dict]     — Queued inputs received while task is running
#                                  Each entry: {"text":str, "speaker_id":str, "source":str}
#   connected_at: datetime      — When this session was created
#   activation_state: str       — "SLEEP" | "ACTIVE" | "SPEAKING" | "INTERRUPTED"
#                                  Controls what happens with incoming audio
#   playback_state: str         — "IDLE" | "PLAYING"
#                                  Controls echo gating in VAD
#   _active_window_handle: asyncio.TimerHandle | None
#                               — Cancel handle for the 30s active window timeout
#
# METHODS:
#
#   async send(self, data: dict):
#     Sends JSON to client via self.websocket.send_json(data)
#
#   reset_active_window_timer(self):
#     Cancels existing timer, schedules new 30s callback to _on_active_timeout.
#     No-op if mode == "meeting" (meeting mode disables timeout).
#
#   async _on_active_timeout(self):
#     Called when 30s silence expires.
#     Sets activation_state = "SLEEP", sends {"type":"sleep"} to client.
#
# FACTORY FUNCTION:
#
#   create_session(user_id: str, websocket: WebSocket) -> Session:
#     Creates a new Session with:
#       - session_id = uuid4
#       - activation_state = "SLEEP"
#       - playback_state = "IDLE"
#       - mode = "normal"
#       - empty working_memory, task_state={"status":"idle"}, empty input_queue
#
# IDENTITY CONTRACT (must stay consistent across the entire stack):
#   user_id    → Authenticated account owner (from JWT). Used for data isolation.
#   speaker_id → Physical speaker track from diarizer. Defaults to user_id for text.
#   persona_id → Context persona loaded for tone/access policy. Mapped by PersonaAgent.
#
# MAPPING RULES:
#   Voice input:  diarizer emits speaker_id → PersonaAgent maps to persona_id
#   Text input:   speaker_id = user_id
#   Context/policy uses persona_id; storage isolation always uses user_id.
#   If mapping fails or low confidence: persona_id = "guest_unknown" (safe fallback)
# =============================================================================

import asyncio
from datetime import datetime
from uuid import uuid4

from fastapi import WebSocket


class Session:
    def __init__(self, session_id: str, user_id: str, websocket: WebSocket):
        self.session_id: str = session_id
        self.user_id: str = user_id
        self.websocket: WebSocket = websocket
        self.client_type: str = "browser"
        self.active_speaker: str = user_id
        self.mode: str = "normal"
        self.working_memory: list[dict] = []
        self.task_state: dict = {"status": "idle"}
        self.input_queue: list[dict] = []
        self.connected_at: datetime = datetime.utcnow()
        self.activation_state: str = "SLEEP"
        self.playback_state: str = "IDLE"
        self._active_window_handle: asyncio.TimerHandle | None = None

    async def send(self, data: dict):
        pass

    def reset_active_window_timer(self):
        pass

    async def _on_active_timeout(self):
        pass


def create_session(user_id: str, websocket: WebSocket) -> Session:
    pass
