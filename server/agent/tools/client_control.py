"""Client control tools - allow agent to control the client."""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def switch_mode(mode: str) -> bool:
    """Switch client to conversation or meeting mode.
    
    Args:
        mode: "conversation" or "meeting"
        
    Returns:
        True if successful
    """
    logger.info(f"Tool call: switch_mode({mode})")
    # TODO: Send mode_switch message to client via WebSocket
    return True


async def set_vad_sensitivity(level: str) -> bool:
    """Adjust VAD sensitivity on client.
    
    Args:
        level: "low", "medium", or "high"
        
    Returns:
        True if successful
    """
    logger.info(f"Tool call: set_vad_sensitivity({level})")
    # TODO: Send VAD sensitivity adjustment to client
    return True


async def mute_microphone() -> bool:
    """Tell client to mute microphone."""
    logger.info("Tool call: mute_microphone()")
    # TODO: Send mute signal to client
    return True


async def unmute_microphone() -> bool:
    """Tell client to unmute microphone."""
    logger.info("Tool call: unmute_microphone()")
    # TODO: Send unmute signal to client
    return True


async def show_in_chat(content: str, content_type: str = "text") -> bool:
    """Push content to chatbot UI on client.
    
    Args:
        content: Content to show
        content_type: "text", "link", "image", "code"
        
    Returns:
        True if successful
    """
    logger.info(f"Tool call: show_in_chat({content_type}, {len(content)} bytes)")
    # TODO: Send content to client chat UI
    return True


async def request_image_from_user() -> bool:
    """Prompt user to upload an image."""
    logger.info("Tool call: request_image_from_user()")
    # TODO: Send request to client to show image upload dialog
    return True


async def set_wake_word_sensitivity(level: float) -> bool:
    """Adjust wake word detection sensitivity.
    
    Args:
        level: Confidence threshold (0.0 - 1.0)
        
    Returns:
        True if successful
    """
    logger.info(f"Tool call: set_wake_word_sensitivity({level})")
    # TODO: Send sensitivity change to client
    return True
