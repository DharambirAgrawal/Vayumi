from __future__ import annotations


class RespondVia:
    VOICE_AND_CHAT = "voice_and_chat"
    CHAT_ONLY = "chat_only"
    VOICE_ONLY = "voice_only"


class InterruptPolicy:
    QUEUE = "queue"
    REPLACE = "replace"


class WsEvent:
    ERROR = "error"
    HELLO = "hello"
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"

    WAKE_WORD_STATUS = "wake_word_status"
    WAKE_WORD_DETECTED = "wake_word_detected"
    WAKE_WORD_REQUIRED = "wake_word_required"
    WAKE_WORD_DEBUG = "wake_word_debug"
    WAKE_WINDOW_OPENED = "wake_window_opened"
    WAKE_WINDOW_CLOSED = "wake_window_closed"

    VAD_SPEECH_START = "vad_speech_start"
    VAD_SPEECH_END = "vad_speech_end"

    TRANSCRIPTION_PARTIAL = "transcription_partial"
    TRANSCRIPTION_FINAL = "transcription_final"
    SPEAKER_IDENTIFIED = "speaker_identified"
    DIARIZATION_SEGMENT = "diarization_segment"

    AGENT_THINKING = "agent_thinking"
    AGENT_RESPONSE_START = "agent_response_start"
    AGENT_RESPONSE_CHUNK = "agent_response_chunk"
    AGENT_RESPONSE_END = "agent_response_end"
    CHATBOT_RESPONSE = "chatbot_response"

    TTS_STREAM_START = "tts_stream_start"
    TTS_STREAM_END = "tts_stream_end"

    INTERRUPT_ACK = "interrupt_ack"
    RESUME_POLICY_CHANGED = "resume_policy_changed"
    MODE_CHANGED = "mode_changed"
    PING = "ping"
    PONG = "pong"


DEFAULT_WAKE_COMMAND_WINDOW_SECONDS = 8
