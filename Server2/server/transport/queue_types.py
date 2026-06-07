from __future__ import annotations

from dataclasses import dataclass

from server.voice.respond_via import RespondVia


@dataclass
class QueuedChat:
    text: str
    prefer_voice: bool = True


@dataclass
class PendingChatDelivery:
    turn_id: str
    assistant_text: str
    respond_via: RespondVia
    prefer_voice: bool
