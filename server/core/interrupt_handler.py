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
        """
        Handle a classified interrupt action: 'stop', 'redirect', or 'add_context'.

        - stop:        Stop TTS, cancel any running task, set ACTIVE state.
        - redirect:    Stop TTS, set ACTIVE state. Caller routes new input onward.
        - add_context: Pause TTS, set INTERRUPTED state. Caller merges context
                       then resumes or regenerates.

        Always resets playback_state to IDLE and restarts the active window timer.
        """
        if action == "stop":
            await self.tts_engine.stop()
            if (hasattr(session, "task_state")
                    and isinstance(session.task_state, dict)
                    and session.task_state.get("status") == "running"):
                session.task_state["status"] = "idle"
            session.activation_state = "ACTIVE"

        elif action == "redirect":
            await self.tts_engine.stop()
            session.activation_state = "ACTIVE"

        elif action == "add_context":
            await self.tts_engine.pause()
            session.activation_state = "INTERRUPTED"

        # Common finalization regardless of action type
        session.playback_state = "IDLE"
        session.reset_active_window_timer()

    async def handle_speech_interrupt(self, session, audio_bytes: bytes):
        """
        Process a speech-based interrupt detected by VAD during SPEAKING state.

        1. Transcribe the audio via the STT engine.
        2. Classify the transcript into an interrupt action.
        3. Execute the interrupt via self.handle().
        4. If the action is 'redirect', identify the speaker and route the
           new input through process_user_turn for further processing.
        """
        # Step 1: transcribe the interrupt speech
        text = await self.stt_engine.transcribe(audio_bytes)

        # Step 2: classify what kind of interrupt this is
        action = self._classify_interrupt(text)

        # Step 3: execute the interrupt handling
        await self.handle(session, action)

        # Step 4: if redirect, identify speaker and route the new input
        if action == "redirect":
            speaker_id = await self.diarizer.identify(
                audio_bytes, session.user_id
            )
            # Late import to avoid circular dependency between
            # server.core.interrupt_handler and server.ws.handler
            from server.ws.handler import process_user_turn
            await process_user_turn(
                session, text, speaker_id, source="voice"
            )

    def _classify_interrupt(self, text: str) -> str:
        """
        Classify transcribed interrupt text into an action type.

        Uses substring matching against known stop and pause phrases.
        Falls back to 'redirect' if the text doesn't match any known
        stop or pause pattern, indicating the user wants to say
        something new.

        Returns:
            'stop'        — user wants to cancel/stop everything
            'add_context' — user wants to pause and add information
            'redirect'    — user is saying something new entirely
        """
        text_lower = text.lower().strip()

        # Check stop words first (higher priority — explicit cancellation)
        if any(w in text_lower for w in STOP_WORDS):
            return "stop"

        # Check pause/hold words
        if any(w in text_lower for w in PAUSE_WORDS):
            return "add_context"

        # Default: treat as new input that should redirect the conversation
        return "redirect"