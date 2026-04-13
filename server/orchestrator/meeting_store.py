from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class MeetingBuffer:
    session_id: str
    segments: list[dict] = field(default_factory=list)
    transcript_lines: list[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)


class MeetingStore:
    def __init__(self):
        self._buffers: dict[str, MeetingBuffer] = {}

    def init(self, session_id: str) -> None:
        self._buffers[session_id] = MeetingBuffer(session_id=session_id)

    def append(self, session_id: str, transcript_line: str) -> None:
        if not transcript_line.strip():
            return
        if session_id not in self._buffers:
            self.init(session_id)
        buf = self._buffers[session_id]
        buf.transcript_lines.append(transcript_line.strip())

    def get_formatted(self, session_id: str) -> str:
        buf = self._buffers.get(session_id)
        if not buf or not buf.transcript_lines:
            return ""
        return "\n".join(buf.transcript_lines[-200:])

    def clear(self, session_id: str) -> None:
        self._buffers.pop(session_id, None)


meeting_store = MeetingStore()
