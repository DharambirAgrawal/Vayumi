"""Session manager for handling multiple client connections."""
import asyncio
from typing import Dict, Optional
from datetime import datetime, timedelta
import logging

from models import Session, ClientType, ClientConnection, AudioConfig

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages active sessions and client connections."""
    
    def __init__(self, session_timeout_seconds: int = 60):
        self.sessions: Dict[str, Session] = {}
        self.session_timeout = session_timeout_seconds
        self.lock = asyncio.Lock()
    
    async def create_session(self) -> Session:
        """Create a new session."""
        async with self.lock:
            session = Session()
            self.sessions[session.session_id] = session
            logger.info(f"Created session: {session.session_id}")
            return session
    
    async def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        async with self.lock:
            session = self.sessions.get(session_id)
            if session:
                session.last_activity = datetime.utcnow()
            return session
    
    async def register_client(
        self,
        session_id: str,
        client_type: ClientType,
        capabilities: list,
        audio_config: Optional[AudioConfig] = None,
    ) -> Optional[Session]:
        """Register a new client connection for a session."""
        async with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return None
            
            if audio_config is None:
                audio_config = AudioConfig()
            
            connection = ClientConnection(
                client_type=client_type,
                session_id=session_id,
                connected_at=datetime.utcnow(),
                capabilities=capabilities,
                audio_config=audio_config,
            )
            
            if client_type == ClientType.WEB:
                session.web_client = connection
            elif client_type == ClientType.HARDWARE:
                session.hardware_client = connection
            
            # Set as voice source if first client
            if session.active_voice_source is None:
                session.active_voice_source = client_type
                logger.info(f"Set {client_type} as voice source for session {session_id}")
            
            logger.info(f"Registered {client_type} client for session {session_id}")
            return session
    
    async def unregister_client(
        self, session_id: str, client_type: ClientType
    ) -> Optional[Session]:
        """Unregister a client from a session."""
        async with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return None
            
            if client_type == ClientType.WEB:
                session.web_client = None
            elif client_type == ClientType.HARDWARE:
                session.hardware_client = None
            
            # If this was the voice source, switch to other client if available
            if session.active_voice_source == client_type:
                if client_type == ClientType.WEB and session.hardware_client:
                    session.active_voice_source = ClientType.HARDWARE
                    logger.info(f"Switched voice source to hardware for session {session_id}")
                elif client_type == ClientType.HARDWARE and session.web_client:
                    session.active_voice_source = ClientType.WEB
                    logger.info(f"Switched voice source to web for session {session_id}")
                else:
                    session.active_voice_source = None
                    logger.info(f"No voice source available for session {session_id}")
            
            # End session if no clients remain
            if not session.has_connected_clients():
                session.last_activity = datetime.utcnow()
                logger.info(
                    f"Session {session_id} now has no clients; "
                    f"retaining until timeout"
                )
            
            return session
    
    async def set_voice_source(
        self, session_id: str, client_type: ClientType
    ) -> bool:
        """Set the active voice source for a session."""
        async with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return False
            
            if not session.can_set_voice_source(client_type):
                logger.warning(f"Cannot set {client_type} as voice source - not connected")
                return False
            
            session.active_voice_source = client_type
            logger.info(f"Voice source set to {client_type} for session {session_id}")
            return True
    
    async def end_session(self, session_id: str) -> bool:
        """End a session."""
        async with self.lock:
            return await self._end_session_internal(session_id)
    
    async def _end_session_internal(self, session_id: str) -> bool:
        """Internal session ending logic (must be called with lock held)."""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Ended session: {session_id}")
            return True
        return False
    
    async def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions."""
        async with self.lock:
            now = datetime.utcnow()
            expired = [
                sid for sid, session in self.sessions.items()
                if (now - session.last_activity).total_seconds() > self.session_timeout
                and not session.has_connected_clients()
            ]
            
            for sid in expired:
                del self.sessions[sid]
            
            if expired:
                logger.info(f"Cleaned up {len(expired)} expired sessions")
            
            return len(expired)
    
    async def get_active_sessions_count(self) -> int:
        """Get count of active sessions with connected clients."""
        async with self.lock:
            return sum(
                1 for session in self.sessions.values()
                if session.has_connected_clients()
            )
