"""Session tools - allow agent to access session data."""
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)


async def get_session_transcript(session_id: str) -> str:
    """Get full transcript for current session.
    
    Args:
        session_id: Session ID
        
    Returns:
        Full transcript text
    """
    logger.info(f"Tool call: get_session_transcript({session_id})")
    try:
        from main import session_manager
    except Exception:
        return ""

    if session_manager is None:
        return ""

    session = await session_manager.get_session(session_id)
    if session is None:
        return ""

    parts: list[str] = []
    for segment in getattr(session, "transcriptions", []):
        text = getattr(segment, "text", "")
        if text:
            parts.append(str(text))
    return "\n".join(parts)


async def get_meeting_summary(session_id: str) -> str:
    """Get summary of meeting with speaker labels.
    
    Args:
        session_id: Session ID
        
    Returns:
        Meeting summary
    """
    logger.info(f"Tool call: get_meeting_summary({session_id})")
    try:
        from main import session_manager
    except Exception:
        return ""

    if session_manager is None:
        return ""

    session = await session_manager.get_session(session_id)
    if session is None:
        return ""

    lines: list[str] = []
    for segment in getattr(session, "meeting_segments", []):
        speaker = getattr(segment, "speaker", None) or "speaker"
        text = getattr(segment, "text", "")
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


async def save_session_note(session_id: str, note: str) -> bool:
    """Save a note to session context.
    
    Args:
        session_id: Session ID
        note: Note text
        
    Returns:
        True if successful
    """
    logger.info(f"Tool call: save_session_note({session_id}, {len(note)} chars)")
    try:
        from main import session_manager
    except Exception:
        return False

    if session_manager is None:
        return False

    session = await session_manager.get_session(session_id)
    if session is None:
        return False

    session.context_notes.append(note)
    return True


async def get_active_client_type(session_id: str) -> Optional[str]:
    """Get type of active voice source client.
    
    Args:
        session_id: Session ID
        
    Returns:
        "web" or "hardware" or None
    """
    logger.info(f"Tool call: get_active_client_type({session_id})")
    try:
        from main import session_manager
    except Exception:
        return None

    if session_manager is None:
        return None

    session = await session_manager.get_session(session_id)
    if session is None or session.active_voice_source is None:
        return None

    return session.active_voice_source.value


async def get_chatbot_attachments(session_id: str) -> List[dict]:
    """Get images/links user sent via chatbot.
    
    Args:
        session_id: Session ID
        
    Returns:
        List of attachment objects
    """
    logger.info(f"Tool call: get_chatbot_attachments({session_id})")
    try:
        from main import session_manager
    except Exception:
        return []

    if session_manager is None:
        return []

    session = await session_manager.get_session(session_id)
    if session is None:
        return []

    return list(getattr(session, "attachments", []))
