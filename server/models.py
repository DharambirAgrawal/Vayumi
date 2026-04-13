"""Data models and enums for Vayumi server."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import uuid


class ClientType(str, Enum):
    """Supported client types."""
    WEB = "web"
    HARDWARE = "hardware"


class Mode(str, Enum):
    """Operating modes."""
    CONVERSATION = "conversation"
    MEETING = "meeting"


class ResumePolicy(str, Enum):
    """How interrupted responses should resume."""
    RESTART_SENTENCE = "restart_sentence"
    CONTINUE_TOKEN_STREAM = "continue_token_stream"
    CONTINUE_CHECKPOINT = "continue_checkpoint"


class ConnectionState(str, Enum):
    """Connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED_IDLE = "connected_idle"
    WAKE_DETECTED = "wake_detected"
    STREAMING_AUDIO = "streaming_audio"
    WAITING_RESPONSE = "waiting_response"
    AI_SPEAKING = "ai_speaking"
    INTERRUPTING = "interrupting"


@dataclass
class AudioConfig:
    """Audio configuration."""
    sample_rate: int = 16000
    channels: int = 1
    bit_depth: int = 16
    chunk_duration_ms: int = 20


@dataclass
class ClientConnection:
    """Represents a connected client."""
    client_type: ClientType
    session_id: str
    connected_at: datetime
    capabilities: List[str] = field(default_factory=list)
    audio_config: AudioConfig = field(default_factory=AudioConfig)


@dataclass
class TranscriptionSegment:
    """A transcription segment."""
    text: str
    start_ms: int
    end_ms: int
    confidence: float
    final: bool = False
    speaker: Optional[str] = None  # For diarization


@dataclass
class Session:
    """Main session dataclass."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[str] = None
    mode: Mode = Mode.CONVERSATION
    active_voice_source: Optional[ClientType] = None
    web_client: Optional[ClientConnection] = None
    hardware_client: Optional[ClientConnection] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    
    # Session data
    transcriptions: List[TranscriptionSegment] = field(default_factory=list)
    context_notes: List[str] = field(default_factory=list)
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    current_response_id: Optional[str] = None
    response_generation: int = 0
    resume_policy: ResumePolicy = ResumePolicy.RESTART_SENTENCE
    last_speaker_label: Optional[str] = None
    last_speaker_confidence: Optional[float] = None
    last_speaker_is_owner: Optional[bool] = None
    current_response_words: List[str] = field(default_factory=list)
    current_response_word_index: int = 0
    current_response_checkpoint_index: int = 0
    pending_resume_words: List[str] = field(default_factory=list)
    pending_resume_response_id: Optional[str] = None
    wake_window_expires_at: Optional[datetime] = None
    wake_window_seconds: int = 8
    wake_word_active: bool = False
    tts_state: "TTSStreamState" = field(default_factory=lambda: TTSStreamState())
    meeting_timeline_ms: int = 0
    meeting_segments: List["DiarizationSegment"] = field(default_factory=list)
    
    # State tracking
    is_vad_active: bool = False
    is_ai_speaking: bool = False
    interrupted: bool = False

    def is_wake_window_open(self) -> bool:
        """Return whether the post-wake command window is currently active."""
        if self.wake_window_expires_at is None:
            return False
        return datetime.utcnow() <= self.wake_window_expires_at

    def open_wake_window(self, seconds: Optional[int] = None) -> None:
        """Open the short command window after wake word detection."""
        duration = seconds if seconds is not None else self.wake_window_seconds
        self.wake_word_active = True
        self.wake_window_expires_at = datetime.utcnow() + timedelta(seconds=duration)

    def close_wake_window(self) -> None:
        """Close the wake command window and go back to sleep."""
        self.wake_word_active = False
        self.wake_window_expires_at = None
    
    def has_connected_clients(self) -> bool:
        """Check if any clients are connected."""
        return self.web_client is not None or self.hardware_client is not None
    
    def get_active_client(self) -> Optional[ClientConnection]:
        """Get the active voice source client."""
        if self.active_voice_source == ClientType.WEB:
            return self.web_client
        elif self.active_voice_source == ClientType.HARDWARE:
            return self.hardware_client
        return None
    
    def can_set_voice_source(self, client_type: ClientType) -> bool:
        """Check if a client can become the voice source."""
        if client_type == ClientType.WEB and self.web_client:
            return True
        if client_type == ClientType.HARDWARE and self.hardware_client:
            return True
        return False


@dataclass
class VayumiError:
    """Error wrapper for protocol."""
    code: str
    message: str
    fatal: bool = False


@dataclass
class ChatMessage:
    """Chat message from user."""
    text: Optional[str] = None
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    respond_via: str = "voice_and_chat"  # "voice_and_chat" | "chat_only" | "voice_only"


@dataclass
class DiarizationSegment:
    """Speaker diarization segment."""
    speaker: str
    text: str
    start_ms: int
    end_ms: int


@dataclass
class TTSStreamState:
    """Tracks TTS stream status for a session."""
    active: bool = False
    response_id: Optional[str] = None
    voice: Optional[str] = None
