"""Test session manager and models."""
import pytest
import asyncio
from datetime import datetime

from session.manager import SessionManager
from models import Session, ClientType, Mode, AudioConfig


@pytest.mark.asyncio
async def test_create_session():
    """Test creating a new session."""
    manager = SessionManager()
    session = await manager.create_session()
    
    assert session is not None
    assert session.session_id
    assert session.mode == Mode.CONVERSATION
    assert session.active_voice_source is None
    assert session.web_client is None
    assert session.hardware_client is None


@pytest.mark.asyncio
async def test_register_web_client():
    """Test registering a web client."""
    manager = SessionManager()
    session = await manager.create_session()
    session_id = session.session_id
    
    audio_config = AudioConfig(sample_rate=16000, channels=1)
    result = await manager.register_client(
        session_id,
        ClientType.WEB,
        ["vad", "wake_word"],
        audio_config,
    )
    
    assert result is not None
    assert result.web_client is not None
    assert result.web_client.client_type == ClientType.WEB
    assert result.active_voice_source == ClientType.WEB
    assert "vad" in result.web_client.capabilities


@pytest.mark.asyncio
async def test_register_multiple_clients():
    """Test registering both web and hardware clients."""
    manager = SessionManager()
    session = await manager.create_session()
    session_id = session.session_id
    
    # Register web client
    await manager.register_client(session_id, ClientType.WEB, ["vad"])
    
    # Register hardware client
    result = await manager.register_client(session_id, ClientType.HARDWARE, [])
    
    assert result.web_client is not None
    assert result.hardware_client is not None
    # Hardware should not become voice source if web already is
    assert result.active_voice_source == ClientType.WEB


@pytest.mark.asyncio
async def test_unregister_client():
    """Test unregistering a client."""
    manager = SessionManager()
    session = await manager.create_session()
    session_id = session.session_id
    
    # Register and then unregister web client
    await manager.register_client(session_id, ClientType.WEB, [])
    result = await manager.unregister_client(session_id, ClientType.WEB)
    
    assert result.web_client is None
    assert result.active_voice_source is None


@pytest.mark.asyncio
async def test_voice_source_switchover():
    """Test switching voice source when primary disconnects."""
    manager = SessionManager()
    session = await manager.create_session()
    session_id = session.session_id
    
    # Register web client (becomes voice source)
    await manager.register_client(session_id, ClientType.WEB, [])
    session = await manager.get_session(session_id)
    assert session.active_voice_source == ClientType.WEB
    
    # Register hardware client
    await manager.register_client(session_id, ClientType.HARDWARE, [])
    session = await manager.get_session(session_id)
    assert session.active_voice_source == ClientType.WEB  # Still web
    
    # Disconnect web client
    await manager.unregister_client(session_id, ClientType.WEB)
    session = await manager.get_session(session_id)
    assert session.active_voice_source == ClientType.HARDWARE  # Switched to hardware


@pytest.mark.asyncio
async def test_session_ends_when_empty():
    """Test that session is retained briefly after last client disconnects."""
    manager = SessionManager()
    session = await manager.create_session()
    session_id = session.session_id
    
    # Register and unregister single client
    await manager.register_client(session_id, ClientType.WEB, [])
    await manager.unregister_client(session_id, ClientType.WEB)
    
    # Session should still exist until timeout cleanup runs
    result = await manager.get_session(session_id)
    assert result is not None


@pytest.mark.asyncio
async def test_get_active_sessions_count():
    """Test counting active sessions."""
    manager = SessionManager()
    
    # Create and connect sessions
    s1 = await manager.create_session()
    s2 = await manager.create_session()
    s3 = await manager.create_session()
    
    # Initially no active sessions
    count = await manager.get_active_sessions_count()
    assert count == 0
    
    # Register clients
    await manager.register_client(s1.session_id, ClientType.WEB, [])
    await manager.register_client(s2.session_id, ClientType.HARDWARE, [])
    
    # Should have 2 active sessions
    count = await manager.get_active_sessions_count()
    assert count == 2


@pytest.mark.asyncio
async def test_session_timeout():
    """Test that expired sessions are cleaned up."""
    manager = SessionManager(session_timeout_seconds=1)
    session = await manager.create_session()
    session_id = session.session_id
    
    # Register a client
    await manager.register_client(session_id, ClientType.WEB, [])
    
    # Wait for client to disconnect (stays with no activity)
    await manager.unregister_client(session_id, ClientType.WEB)
    
    # Wait for timeout
    await asyncio.sleep(1.1)
    
    # Cleanup should remove the session
    cleaned = await manager.cleanup_expired_sessions()
    assert cleaned == 1
    
    # Session should be gone
    result = await manager.get_session(session_id)
    assert result is None
