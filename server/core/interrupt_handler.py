# =============================================================================
# server/core/interrupt_handler.py — Interrupt Detection & Handling
# =============================================================================
#
# PURPOSE:
#   Handles user interruptions during Vayumi's speech. Classifies interrupt
#   type and dispatches appropriate action (stop, redirect, add_context).
#
# INTERRUPT TYPES:
#   "stop"        — User says "stop", "quit", "cancel", "shut up", "be quiet", "enough"
#                    Action: Stop TTS, cancel running task, set ACTIVE state
#   "redirect"    — User says something new (not a stop/pause word)
#                    Action: Stop TTS, set ACTIVE, route new input through process_user_turn
#   "add_context" — User says "wait", "hold on", "pause", "one sec", "hang on"
#                    Action: Pause TTS, set INTERRUPTED state, caller merges context
#                    then resumes TTS or regenerates response
#
# CLASS: InterruptHandler
#
#   __init__(self, tts_engine, stt_engine, diarizer):
#     Stores references to TTS (for stop/pause/resume), STT (for transcribing
#     interrupt speech), and diarizer (for identifying who interrupted).
#
#   async handle(self, session, action: str):
#     Handles a typed interrupt action. Called by:
#       - handle_interrupt in ws/handler.py (client button press)
#       - handle_speech_interrupt below (after classifying speech)
#     Logic per action:
#       "stop":
#         - await tts_engine.stop()
#         - If session.task_state["status"] == "running" → set to idle
#         - session.activation_state = "ACTIVE"
#       "redirect":
#         - await tts_engine.stop()
#         - session.activation_state = "ACTIVE"
#         - Caller routes new input to process_user_turn
#       "add_context":
#         - await tts_engine.pause()
#         - session.activation_state = "INTERRUPTED"
#         - Caller merges context, then resume or regenerate
#     Always:
#       - session.playback_state = "IDLE"
#       - session.reset_active_window_timer()
#
#   async handle_speech_interrupt(self, session, audio_bytes: bytes):
#     Called when VAD detects speech during SPEAKING state.
#     Steps:
#       1. Transcribe speech via stt_engine.transcribe(audio_bytes)
#       2. Classify interrupt type via _classify_interrupt(text)
#       3. Call self.handle(session, action)
#       4. If action == "redirect":
#            - Identify speaker via diarizer.identify(audio_bytes, session.user_id)
#            - Call process_user_turn(session, text, speaker_id, source="voice")
#              (imported from ws/handler to avoid circular: pass as callback or late import)
#
#   def _classify_interrupt(self, text: str) -> str:
#     Classifies transcribed interrupt speech into action type.
#     stop_words = {"stop", "quit", "cancel", "shut up", "be quiet", "enough"}
#     pause_words = {"wait", "hold on", "pause", "one sec", "hang on"}
#     text_lower = text.lower().strip()
#     if any(w in text_lower for w in stop_words): return "stop"
#     if any(w in text_lower for w in pause_words): return "add_context"
#     return "redirect"
#
# IMPORTS NEEDED:
# =============================================================================

from server.voice.tts import TTSEngine
from server.voice.stt import STTEngine
from server.voice.diarizer import SpeakerIdentifier

STOP_WORDS = {"stop", "quit", "cancel", "shut up", "be quiet", "enough"}
PAUSE_WORDS = {"wait", "hold on", "pause", "one sec", "hang on"}


class InterruptHandler:
    def __init__(self, tts_engine: TTSEngine, stt_engine: STTEngine,
                 diarizer: SpeakerIdentifier):
        self.tts_engine = tts_engine
        self.stt_engine = stt_engine
        self.diarizer = diarizer

    async def handle(self, session, action: str):
        pass

    async def handle_speech_interrupt(self, session, audio_bytes: bytes):
        pass

    def _classify_interrupt(self, text: str) -> str:
        pass
