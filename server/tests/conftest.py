"""Test configuration and fixtures."""
import pytest
import asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient

import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from main import app
from session.manager import SessionManager
from audio.pipeline import AudioPipeline


@pytest.fixture
def client():
    """Test client for sync endpoints."""
    return TestClient(app)


@pytest.fixture
async def async_client():
    """Async test client for WebSocket."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
async def session_manager():
    """Create a session manager for testing."""
    manager = SessionManager(session_timeout_seconds=60)
    yield manager


@pytest.fixture
async def audio_pipeline():
    """Create an audio pipeline for testing."""
    pipeline = AudioPipeline(sample_rate=16000)
    yield pipeline


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
