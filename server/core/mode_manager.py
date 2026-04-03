# =============================================================================
# server/core/mode_manager.py — Mode Switching (Per-Session)
# =============================================================================

import re
import time
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from server.llm.router import LLMRouter


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class MeetingTranscriptEntry:
    """Single entry in a meeting transcript."""
    timestamp: float
    speaker_id: str
    text: str
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "speaker_id": self.speaker_id,
            "text": self.text,
            "time_formatted": datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S")
        }


@dataclass
class MeetingSummary:
    """Generated meeting summary."""
    title: str
    start_time: float
    end_time: float
    duration_minutes: float
    participants: list[str]
    summary: str
    key_points: list[str]
    action_items: list[dict]
    transcript: list[dict]
    
    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_minutes": self.duration_minutes,
            "participants": self.participants,
            "summary": self.summary,
            "key_points": self.key_points,
            "action_items": self.action_items,
            "transcript": self.transcript
        }


@dataclass 
class ModeState:
    """State container for mode-specific data."""
    mode_name: str
    entered_at: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)


# =============================================================================
# FLAG DEFINITIONS
# =============================================================================

class FlagPriority:
    """Priority levels for flags/notifications."""
    CRITICAL = 1    # Always shown (emergencies, urgent reminders)
    HIGH = 2        # Important but not urgent
    NORMAL = 3      # Standard notifications
    LOW = 4         # Informational, can be deferred


# =============================================================================
# BASE MODE CLASS
# =============================================================================

class BaseMode(ABC):
    """
    Base class for all behavioral modes.
    
    Modes change global behavior without changing core architecture.
    Each mode can customize:
    - Enter/exit behavior
    - Response filtering
    - Flag filtering
    - Context budget
    """
    
    name: str = "base"
    context_budget: int = 2500  # Default token budget
    
    def on_enter(self, session) -> str | None:
        """
        Called when entering this mode.
        
        Args:
            session: The user session
            
        Returns:
            Optional confirmation message to speak
        """
        pass
    
    def on_exit(self, session) -> str | None:
        """
        Called when exiting this mode.
        
        Args:
            session: The user session
            
        Returns:
            Optional exit message to speak
        """
        pass
    
    def should_respond(self, session, text: str, speaker_id: str | None = None) -> bool:
        """
        Determine if Vayumi should respond to this input.
        
        Args:
            session: The user session
            text: The input text
            speaker_id: ID of the speaker (if known)
            
        Returns:
            True if should respond, False to stay silent
        """
        return True
    
    def filter_flags(self, flags: list[dict]) -> list[dict]:
        """
        Filter incoming flags/notifications based on mode.
        
        Args:
            flags: List of flag dicts with 'priority' key
            
        Returns:
            Filtered list of flags to show
        """
        return flags
    
    def process_input(self, session, text: str, speaker_id: str | None = None) -> None:
        """
        Process input for mode-specific tracking (e.g., meeting transcript).
        
        Args:
            session: The user session
            text: The input text
            speaker_id: ID of the speaker
        """
        pass
    
    def get_context_modifier(self, session) -> dict:
        """
        Get mode-specific context modifications.
        
        Returns:
            Dict of context overrides/additions
        """
        return {}


# =============================================================================
# NORMAL MODE
# =============================================================================

class NormalMode(BaseMode):
    """
    Default mode — full conversational capability.
    
    - All skills and tools available
    - Balanced context budget (~2500 tokens)
    - Responds to authenticated user
    """
    
    name = "normal"
    context_budget = 2500
    
    def on_enter(self, session) -> str | None:
        # No special setup needed
        session.mode_state = ModeState(mode_name="normal")
        return None
    
    def on_exit(self, session) -> str | None:
        # No special teardown
        return None
    
    def should_respond(self, session, text: str, speaker_id: str | None = None) -> bool:
        # Always respond to authenticated user
        return True


# =============================================================================
# MEETING MODE
# =============================================================================

class MeetingMode(BaseMode):
    """
    Meeting mode — optimized for meeting scenarios.
    
    - Diarizer sensitivity increased
    - Everything transcribed with speaker + timestamp
    - Minimal verbal responses (avoid disrupting meeting)
    - Only responds when directly called by name
    - Generates meeting summary on exit
    """
    
    name = "meeting"
    context_budget = 3500  # Higher budget for meeting context
    
    # Patterns that indicate direct address to Vayumi
    WAKE_PATTERNS = [
        r'\bvayumi\b',
        r'\bhey vayumi\b',
        r'\bok vayumi\b',
        r'\bvayumi[\s,]+',
    ]
    
    # Compiled patterns for efficiency
    _wake_regex = None
    
    @classmethod
    def _get_wake_regex(cls):
        if cls._wake_regex is None:
            pattern = '|'.join(cls.WAKE_PATTERNS)
            cls._wake_regex = re.compile(pattern, re.IGNORECASE)
        return cls._wake_regex
    
    def on_enter(self, session) -> str | None:
        """Initialize meeting mode."""
        # Initialize meeting state
        session.mode_state = ModeState(
            mode_name="meeting",
            entered_at=time.time(),
            data={
                "transcript": [],
                "participants": set(),
                "start_time": time.time(),
                "title": None,
                "active_window_disabled": True
            }
        )
        
        # Disable active window timer (meeting stays active indefinitely)
        if hasattr(session, 'active_window_timer'):
            session.active_window_timer_backup = session.active_window_timer
            session.active_window_timer = None
        
        return "Meeting mode activated. I'll transcribe everything and stay quiet unless you call my name."
    
    def on_exit(self, session) -> str | None:
        """
        Generate meeting summary and clean up.
        
        Note: The actual summary generation is async and handled by ModeManager.
        This just prepares the state.
        """
        # Re-enable active window timer
        if hasattr(session, 'active_window_timer_backup'):
            session.active_window_timer = session.active_window_timer_backup
            delattr(session, 'active_window_timer_backup')
        
        # Mark end time
        if session.mode_state and session.mode_state.data:
            session.mode_state.data["end_time"] = time.time()
        
        return "Meeting mode ended. Generating summary..."
    
    def should_respond(self, session, text: str, speaker_id: str | None = None) -> bool:
        """Only respond if directly addressed by name."""
        return bool(self._get_wake_regex().search(text))
    
    def process_input(self, session, text: str, speaker_id: str | None = None) -> None:
        """Add entry to meeting transcript."""
        if not session.mode_state or not session.mode_state.data:
            return
        
        entry = MeetingTranscriptEntry(
            timestamp=time.time(),
            speaker_id=speaker_id or "unknown",
            text=text
        )
        
        session.mode_state.data["transcript"].append(entry)
        
        # Track participants
        if speaker_id:
            session.mode_state.data["participants"].add(speaker_id)
    
    def filter_flags(self, flags: list[dict]) -> list[dict]:
        """Only allow critical flags during meetings."""
        return [f for f in flags if f.get("priority", FlagPriority.NORMAL) <= FlagPriority.CRITICAL]
    
    def get_context_modifier(self, session) -> dict:
        """Add meeting context."""
        if not session.mode_state or not session.mode_state.data:
            return {}
        
        data = session.mode_state.data
        duration = time.time() - data.get("start_time", time.time())
        
        return {
            "mode": "meeting",
            "meeting_duration_minutes": round(duration / 60, 1),
            "participant_count": len(data.get("participants", set())),
            "transcript_length": len(data.get("transcript", [])),
            "instruction": "Keep responses brief. Only speak when directly addressed."
        }
    
    def get_transcript(self, session) -> list[dict]:
        """Get the full meeting transcript."""
        if not session.mode_state or not session.mode_state.data:
            return []
        
        transcript = session.mode_state.data.get("transcript", [])
        return [entry.to_dict() for entry in transcript]
    
    def get_participants(self, session) -> list[str]:
        """Get list of meeting participants."""
        if not session.mode_state or not session.mode_state.data:
            return []
        
        return list(session.mode_state.data.get("participants", set()))


# =============================================================================
# FOCUS MODE
# =============================================================================

class FocusMode(BaseMode):
    """
    Focus mode — minimal interruptions.
    
    - No proactive interruptions
    - Responses only on direct questions
    - Filters non-critical flags
    - Minimizes context switching overhead
    """
    
    name = "focus"
    context_budget = 2000  # Reduced budget for efficiency
    
    # Patterns indicating a direct question
    QUESTION_PATTERNS = [
        r'\?$',  # Ends with question mark
        r'^(what|who|where|when|why|how|can|could|would|should|is|are|do|does|did)\b',
        r'\bvayumi\b',  # Direct address
    ]
    
    _question_regex = None
    
    @classmethod
    def _get_question_regex(cls):
        if cls._question_regex is None:
            pattern = '|'.join(cls.QUESTION_PATTERNS)
            cls._question_regex = re.compile(pattern, re.IGNORECASE)
        return cls._question_regex
    
    def on_enter(self, session) -> str | None:
        """Enter focus mode."""
        session.mode_state = ModeState(
            mode_name="focus",
            entered_at=time.time(),
            data={
                "flag_filter": "critical_only",
                "proactive_disabled": True
            }
        )
        
        return "Focus mode activated. I'll only respond to direct questions."
    
    def on_exit(self, session) -> str | None:
        """Exit focus mode."""
        return "Focus mode deactivated. Back to normal."
    
    def should_respond(self, session, text: str, speaker_id: str | None = None) -> bool:
        """Only respond to direct questions or explicit address."""
        return bool(self._get_question_regex().search(text))
    
    def filter_flags(self, flags: list[dict]) -> list[dict]:
        """Only allow critical and high priority flags."""
        return [f for f in flags if f.get("priority", FlagPriority.NORMAL) <= FlagPriority.HIGH]
    
    def get_context_modifier(self, session) -> dict:
        """Add focus mode context."""
        return {
            "mode": "focus",
            "instruction": "Be concise. User is focusing. Avoid unnecessary elaboration."
        }


# =============================================================================
# MODE MANAGER
# =============================================================================

class ModeManager:
    """
    Manages behavioral modes for user sessions.
    
    Modes are per-session (per-user). The manager handles:
    - Mode switching with enter/exit callbacks
    - Mode-specific behavior delegation
    - Meeting summary generation
    """
    
    MODES: dict[str, BaseMode] = {
        "normal": NormalMode(),
        "meeting": MeetingMode(),
        "focus": FocusMode(),
    }
    
    DEFAULT_MODE = "normal"
    
    def __init__(self, llm_router: LLMRouter | None = None, memory_store=None):
        """
        Initialize mode manager.
        
        Args:
            llm_router: LLM router for summary generation
            memory_store: Memory store for saving meeting data
        """
        self.llm_router = llm_router
        self.memory_store = memory_store
    
    def get_mode(self, session) -> BaseMode:
        """Get the current mode for a session."""
        mode_name = getattr(session, 'mode', self.DEFAULT_MODE)
        return self.MODES.get(mode_name, self.MODES[self.DEFAULT_MODE])
    
    def switch(
        self,
        session,
        mode_name: str,
        trigger: str = "voice"
    ) -> str | None:
        """
        Switch session to a new mode.
        
        Args:
            session: The user session
            mode_name: Target mode name
            trigger: How the switch was triggered ("voice", "button", "auto")
            
        Returns:
            Confirmation message (if any)
        """
        if mode_name not in self.MODES:
            return f"Unknown mode: {mode_name}. Available modes: {', '.join(self.MODES.keys())}"
        
        old_mode_name = getattr(session, 'mode', self.DEFAULT_MODE)
        
        # Skip if already in target mode
        if old_mode_name == mode_name:
            return f"Already in {mode_name} mode."
        
        old_mode = self.MODES.get(old_mode_name, self.MODES[self.DEFAULT_MODE])
        new_mode = self.MODES[mode_name]
        
        # Exit old mode
        exit_message = old_mode.on_exit(session)
        
        # Update session mode
        session.mode = mode_name
        
        # Enter new mode
        enter_message = new_mode.on_enter(session)
        
        # Log the switch
        self._log_mode_switch(session, old_mode_name, mode_name, trigger)
        
        # Combine messages
        messages = [m for m in [exit_message, enter_message] if m]
        return " ".join(messages) if messages else f"Switched to {mode_name} mode."
    
    def should_respond(
        self,
        session,
        text: str,
        speaker_id: str | None = None
    ) -> bool:
        """Check if Vayumi should respond based on current mode."""
        mode = self.get_mode(session)
        return mode.should_respond(session, text, speaker_id)
    
    def process_input(
        self,
        session,
        text: str,
        speaker_id: str | None = None
    ) -> None:
        """Process input for mode-specific tracking."""
        mode = self.get_mode(session)
        mode.process_input(session, text, speaker_id)
    
    def filter_flags(self, session, flags: list[dict]) -> list[dict]:
        """Filter flags based on current mode."""
        mode = self.get_mode(session)
        return mode.filter_flags(flags)
    
    def get_context_modifier(self, session) -> dict:
        """Get mode-specific context modifications."""
        mode = self.get_mode(session)
        return mode.get_context_modifier(session)
    
    def get_context_budget(self, session) -> int:
        """Get context token budget for current mode."""
        mode = self.get_mode(session)
        return mode.context_budget
    
    async def generate_meeting_summary(self, session) -> MeetingSummary | None:
        """
        Generate a summary for a completed meeting.
        
        Called when exiting meeting mode.
        """
        if not self.llm_router:
            return None
        
        meeting_mode = self.MODES.get("meeting")
        if not isinstance(meeting_mode, MeetingMode):
            return None
        
        transcript = meeting_mode.get_transcript(session)
        participants = meeting_mode.get_participants(session)
        
        if not transcript:
            return None
        
        # Build transcript text
        transcript_text = "\n".join([
            f"[{entry['time_formatted']}] {entry['speaker_id']}: {entry['text']}"
            for entry in transcript
        ])
        
        # Generate summary via LLM
        messages = [
            {
                "role": "system",
                "content": """You are a meeting summarizer. Analyze the transcript and provide:
1. A brief title for the meeting
2. A 2-3 sentence summary
3. Key points discussed (bullet list)
4. Action items with assignees if mentioned

Respond in JSON format:
{
  "title": "...",
  "summary": "...",
  "key_points": ["...", "..."],
  "action_items": [{"task": "...", "assignee": "..." or null}]
}"""
            },
            {
                "role": "user",
                "content": f"Meeting transcript:\n\n{transcript_text}"
            }
        ]
        
        try:
            response = await self.llm_router.call(
                user_id=session.user_id,
                task_type="orchestrate",
                messages=messages,
                max_tokens=1000
            )
            
            # Parse response
            import json
            data = json.loads(response)
            
            start_time = session.mode_state.data.get("start_time", time.time())
            end_time = session.mode_state.data.get("end_time", time.time())
            
            summary = MeetingSummary(
                title=data.get("title", "Untitled Meeting"),
                start_time=start_time,
                end_time=end_time,
                duration_minutes=round((end_time - start_time) / 60, 1),
                participants=participants,
                summary=data.get("summary", ""),
                key_points=data.get("key_points", []),
                action_items=data.get("action_items", []),
                transcript=transcript
            )
            
            # Store in memory if available
            if self.memory_store:
                await self._store_meeting_summary(session, summary)
            
            return summary
            
        except Exception:
            # Return basic summary on error
            start_time = session.mode_state.data.get("start_time", time.time())
            end_time = time.time()
            
            return MeetingSummary(
                title="Meeting",
                start_time=start_time,
                end_time=end_time,
                duration_minutes=round((end_time - start_time) / 60, 1),
                participants=participants,
                summary=f"Meeting with {len(transcript)} exchanges.",
                key_points=[],
                action_items=[],
                transcript=transcript
            )
    
    async def _store_meeting_summary(self, session, summary: MeetingSummary) -> None:
        """Store meeting summary in memory systems."""
        if not self.memory_store:
            return
        
        try:
            # Store in episodic memory (ChromaDB)
            await self.memory_store.store_episodic(
                user_id=session.user_id,
                content=summary.summary,
                metadata={
                    "type": "meeting_summary",
                    "title": summary.title,
                    "duration_minutes": summary.duration_minutes,
                    "participant_count": len(summary.participants),
                    "action_item_count": len(summary.action_items),
                    "timestamp": summary.start_time
                }
            )
            
            # Store action items separately for easy retrieval
            for item in summary.action_items:
                await self.memory_store.store_episodic(
                    user_id=session.user_id,
                    content=f"Action item from meeting '{summary.title}': {item['task']}",
                    metadata={
                        "type": "action_item",
                        "meeting_title": summary.title,
                        "assignee": item.get("assignee"),
                        "timestamp": summary.start_time
                    }
                )
        except Exception:
            pass  # Don't fail if memory storage fails
    
    def _log_mode_switch(
        self,
        session,
        old_mode: str,
        new_mode: str,
        trigger: str
    ) -> None:
        """Log mode switch for analytics/debugging."""
        # In production, this would log to your logging system
        pass
    
    def detect_mode_command(self, text: str) -> str | None:
        """
        Detect if text contains a mode switch command.
        
        Args:
            text: User input text
            
        Returns:
            Mode name if command detected, None otherwise
        """
        text_lower = text.lower().strip()
        
        # Meeting mode triggers
        if any(phrase in text_lower for phrase in [
            "meeting mode",
            "start meeting",
            "begin meeting",
            "enter meeting mode"
        ]):
            return "meeting"
        
        # End meeting triggers
        if any(phrase in text_lower for phrase in [
            "end meeting",
            "stop meeting",
            "exit meeting mode",
            "meeting over"
        ]):
            return "normal"
        
        # Focus mode triggers
        if any(phrase in text_lower for phrase in [
            "focus mode",
            "enter focus mode",
            "i need to focus",
            "do not disturb"
        ]):
            return "focus"
        
        # Exit focus mode
        if any(phrase in text_lower for phrase in [
            "exit focus mode",
            "stop focus mode",
            "normal mode",
            "back to normal"
        ]):
            return "normal"
        
        return None