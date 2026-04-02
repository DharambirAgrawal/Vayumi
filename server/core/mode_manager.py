# =============================================================================
# server/core/mode_manager.py — Mode Switching (Per-Session)
# =============================================================================
#
# PURPOSE:
#   Manages Vayumi's behavioral modes. Modes change global behavior without
#   changing the core architecture. Mode state is per-session (per-user).
#
# MODES:
#
#   "normal" (Default) — NormalMode:
#     - Full conversational capability
#     - All skills and tools available
#     - Balanced context budget (~2500 tokens)
#     - Responds to authenticated user
#     on_enter(session): No special setup
#     on_exit(session): No special teardown
#
#   "meeting" — MeetingMode:
#     Activation: "Vayumi, meeting mode" or button press
#     - Diarizer sensitivity increased (capture all speakers)
#     - Everything transcribed with speaker + timestamp
#     - Minimal verbal responses (avoid disrupting the meeting)
#     - Background: builds structured meeting notes in session
#     - Smart interruption: only responds if directly called by name
#     - Active window timer DISABLED (stays active for entire meeting)
#     - On meeting end: "Vayumi, end meeting" →
#         generates full meeting summary + action items
#         stores in episodic memory (owned by authenticated user)
#     on_enter(session):
#       - Cancel active window timer (meeting stays active indefinitely)
#       - Initialize meeting transcript list in session
#       - Set meeting start time
#     on_exit(session):
#       - Generate meeting summary via LLM
#       - Store summary + action items in SQLite meetings table (user-scoped)
#       - Store in episodic memory (ChromaDB, user-scoped)
#       - Re-enable active window timer
#
#   "focus" — FocusMode:
#     Activation: "Vayumi, focus mode"
#     - No proactive interruptions
#     - Responses only on direct questions
#     - Filters non-critical flag injections
#     - Minimizes context switching overhead
#     on_enter(session): Set flag filter to critical-only
#     on_exit(session): Restore flag filter to default
#
# CLASS: ModeManager
#
#   MODES: dict = {
#     "normal": NormalMode(),
#     "meeting": MeetingMode(),
#     "focus": FocusMode(),
#   }
#
#   switch(self, session, mode_name: str, trigger: str = "voice"):
#     1. Get old_mode from session.mode
#     2. Call MODES[old_mode].on_exit(session)
#     3. Set session.mode = mode_name
#     4. Call MODES[mode_name].on_enter(session)
#
# BASE CLASS: BaseMode
#   on_enter(self, session): pass
#   on_exit(self, session): pass
#   should_respond(self, session, text: str) -> bool: return True
#   filter_flags(self, flags: list) -> list: return flags
#
# IMPORTS NEEDED:
# =============================================================================

from abc import ABC, abstractmethod


class BaseMode(ABC):
    def on_enter(self, session):
        pass

    def on_exit(self, session):
        pass

    def should_respond(self, session, text: str) -> bool:
        return True

    def filter_flags(self, flags: list) -> list:
        return flags


class NormalMode(BaseMode):
    pass


class MeetingMode(BaseMode):
    def on_enter(self, session):
        pass

    def on_exit(self, session):
        pass

    def should_respond(self, session, text: str) -> bool:
        pass


class FocusMode(BaseMode):
    def on_enter(self, session):
        pass

    def on_exit(self, session):
        pass

    def filter_flags(self, flags: list) -> list:
        pass


class ModeManager:
    MODES = {
        "normal": NormalMode(),
        "meeting": MeetingMode(),
        "focus": FocusMode(),
    }

    def switch(self, session, mode_name: str, trigger: str = "voice"):
        pass
